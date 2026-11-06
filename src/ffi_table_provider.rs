//! Table providers imported over the datafusion-python FFI protocol.
//!
//! An `FFI_TableProvider` carries a logical extension codec, and that codec
//! carries an `FFI_TaskContextProvider` which holds its provider *weakly*: the
//! foreign side upgrades it on every `scan` and `supports_filters_pushdown` to
//! decode filters. If the host binds it straight to its `SessionContext`, a
//! query planned on a DataFrame fails with "TaskContextProvider went out of
//! scope" once the Python `SessionContext` is collected, even though every
//! other kind of table keeps working through the DataFrame's own state.
//!
//! [`HostedFfiTableProvider`] keeps the codec valid for as long as the table
//! lives, without retaining the `SessionContext` (which would close the cycle
//! `SessionContext -> catalog -> table -> codec -> SessionContext`):
//!
//! - `scan` and `insert_into` rebind the codec to the task context of the
//!   session doing the planning, kept alive for the duration of the call.
//! - The calls that get no session (`supports_filters_pushdown`) use a codec
//!   bound to [`HostTaskContext`], which the table owns: it follows the live
//!   `SessionContext` while there is one, and falls back to a snapshot taken
//!   at registration afterwards.

use std::fmt;
use std::sync::{Arc, RwLock, Weak};

use async_trait::async_trait;
use datafusion::arrow::datatypes::SchemaRef;
use datafusion::catalog::Session;
use datafusion::datasource::{TableProvider, TableType};
use datafusion::error::Result;
use datafusion::execution::context::SessionContext;
use datafusion::execution::{TaskContext, TaskContextProvider};
use datafusion::logical_expr::dml::InsertOp;
use datafusion::physical_plan::ExecutionPlan;
use datafusion_common::Statistics;
use datafusion_expr::{Expr, TableProviderFilterPushDown};
use datafusion_ffi::proto::logical_extension_codec::FFI_LogicalExtensionCodec;
use datafusion_ffi::table_provider::FFI_TableProvider;
use datafusion_proto::logical_plan::DefaultLogicalExtensionCodec;
use tokio::runtime::Handle;

/// Task context for codec calls made outside of a planning session.
///
/// Once the `SessionContext` is gone, it serves the most recent task context
/// it has seen: from the live context, or from the last session that planned
/// a scan of this table. A UDF registered after that point is unknown to it,
/// so a pushdown check on a filter using such a UDF can still fail; only the
/// first query planned after the context is dropped is exposed to this.
struct HostTaskContext {
    session: Weak<SessionContext>,
    fallback: RwLock<Arc<TaskContext>>,
}

impl HostTaskContext {
    fn remember(&self, task_ctx: &Arc<TaskContext>) {
        *self.fallback.write().unwrap_or_else(|e| e.into_inner()) = Arc::clone(task_ctx);
    }
}

impl TaskContextProvider for HostTaskContext {
    fn task_ctx(&self) -> Arc<TaskContext> {
        match self.session.upgrade() {
            Some(ctx) => {
                let task_ctx = ctx.task_ctx();
                self.remember(&task_ctx);
                task_ctx
            }
            None => Arc::clone(&self.fallback.read().unwrap_or_else(|e| e.into_inner())),
        }
    }
}

/// Task context of the session planning a single scan.
struct SessionTaskContext(Arc<TaskContext>);

impl TaskContextProvider for SessionTaskContext {
    fn task_ctx(&self) -> Arc<TaskContext> {
        Arc::clone(&self.0)
    }
}

pub struct HostedFfiTableProvider {
    /// The foreign provider, with its codec bound to `task_ctx`.
    ffi: FFI_TableProvider,
    inner: Arc<dyn TableProvider>,
    /// Strong owner of the provider the codec in `ffi` points to weakly.
    task_ctx: Arc<HostTaskContext>,
    runtime: Option<Handle>,
}

impl fmt::Debug for HostedFfiTableProvider {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("HostedFfiTableProvider")
            .field("ffi", &self.ffi)
            .finish_non_exhaustive()
    }
}

/// The returned codec refers to `task_ctx` weakly: it shares the allocation,
/// so it stays valid exactly as long as some clone of `task_ctx` is alive.
fn codec_for<T: TaskContextProvider + 'static>(
    task_ctx: &Arc<T>,
    runtime: Option<Handle>,
) -> FFI_LogicalExtensionCodec {
    let task_ctx: Arc<dyn TaskContextProvider> = Arc::clone(task_ctx) as _;
    FFI_LogicalExtensionCodec::new(
        Arc::new(DefaultLogicalExtensionCodec {}),
        runtime,
        &task_ctx,
    )
}

impl HostedFfiTableProvider {
    pub fn new(
        ffi: &FFI_TableProvider,
        ctx: &Arc<SessionContext>,
        runtime: Option<Handle>,
    ) -> Self {
        let task_ctx = Arc::new(HostTaskContext {
            session: Arc::downgrade(ctx),
            fallback: RwLock::new(ctx.task_ctx()),
        });
        let mut ffi = ffi.clone();
        ffi.logical_codec = codec_for(&task_ctx, runtime.clone());
        let inner: Arc<dyn TableProvider> = (&ffi).into();
        Self {
            ffi,
            inner,
            task_ctx,
            runtime,
        }
    }

    /// The foreign provider with its codec bound to `task_ctx`. The caller
    /// must keep `task_ctx` alive while the returned provider is in use.
    fn bound_to(&self, task_ctx: &Arc<SessionTaskContext>) -> Arc<dyn TableProvider> {
        let mut ffi = self.ffi.clone();
        ffi.logical_codec = codec_for(task_ctx, self.runtime.clone());
        (&ffi).into()
    }
}

impl HostedFfiTableProvider {
    /// Task context of `session`, also kept as the fallback for later calls
    /// that get no session.
    fn session_task_ctx(&self, session: &dyn Session) -> Arc<SessionTaskContext> {
        let task_ctx = session.task_ctx();
        self.task_ctx.remember(&task_ctx);
        Arc::new(SessionTaskContext(task_ctx))
    }
}

#[async_trait]
impl TableProvider for HostedFfiTableProvider {
    fn schema(&self) -> SchemaRef {
        self.inner.schema()
    }

    fn table_type(&self) -> TableType {
        self.inner.table_type()
    }

    fn statistics(&self) -> Option<Statistics> {
        self.inner.statistics()
    }

    async fn scan(
        &self,
        session: &dyn Session,
        projection: Option<&Vec<usize>>,
        filters: &[Expr],
        limit: Option<usize>,
    ) -> Result<Arc<dyn ExecutionPlan>> {
        let task_ctx = self.session_task_ctx(session);
        let provider = self.bound_to(&task_ctx);
        provider.scan(session, projection, filters, limit).await
    }

    fn supports_filters_pushdown(
        &self,
        filters: &[&Expr],
    ) -> Result<Vec<TableProviderFilterPushDown>> {
        self.inner.supports_filters_pushdown(filters)
    }

    async fn insert_into(
        &self,
        session: &dyn Session,
        input: Arc<dyn ExecutionPlan>,
        insert_op: InsertOp,
    ) -> Result<Arc<dyn ExecutionPlan>> {
        let task_ctx = self.session_task_ctx(session);
        let provider = self.bound_to(&task_ctx);
        provider.insert_into(session, input, insert_op).await
    }
}
