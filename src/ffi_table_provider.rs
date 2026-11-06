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
use datafusion_ffi::table_provider::{FFI_TableProvider, ForeignTableProvider};
use datafusion_proto::logical_plan::LogicalExtensionCodec;
use tokio::runtime::Handle;

/// Task context for codec calls made outside of a planning session.
///
/// While the `SessionContext` is alive, it serves the context's current task
/// context and remembers it. Once the context is gone, it serves the last one
/// remembered: the registry as of the last pushdown check made while the
/// context was alive (or as of registration, if there was none). A pushdown
/// check on a filter using a UDF registered after that point fails to decode.
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

/// Task context of the session planning a single scan or insert.
struct SessionTaskContext(Arc<TaskContext>);

impl TaskContextProvider for SessionTaskContext {
    fn task_ctx(&self) -> Arc<TaskContext> {
        Arc::clone(&self.0)
    }
}

pub struct HostedFfiTableProvider {
    /// The imported provider, with its codec bound to `task_ctx`.
    inner: Arc<dyn TableProvider>,
    /// The provider's own extension codec, kept when the codec is rebound.
    extension_codec: Arc<dyn LogicalExtensionCodec>,
    /// Strong owner of the provider the codec in `inner` points to weakly.
    _task_ctx: Arc<HostTaskContext>,
    runtime: Option<Handle>,
}

impl fmt::Debug for HostedFfiTableProvider {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("HostedFfiTableProvider")
            .field("inner", &self.inner)
            .finish_non_exhaustive()
    }
}

/// Wraps `codec` for FFI with `task_ctx` as its task context provider. A codec
/// that is itself foreign is re-exported as-is, with only the task context
/// swapped. The result refers to `task_ctx` weakly: it shares the allocation,
/// so it stays valid exactly as long as some clone of `task_ctx` is alive.
pub(crate) fn codec_for<T: TaskContextProvider + 'static>(
    codec: Arc<dyn LogicalExtensionCodec>,
    task_ctx: &Arc<T>,
    runtime: Option<Handle>,
) -> FFI_LogicalExtensionCodec {
    let task_ctx: Arc<dyn TaskContextProvider> = Arc::clone(task_ctx) as _;
    FFI_LogicalExtensionCodec::new(codec, runtime, &task_ctx)
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
        let extension_codec: Arc<dyn LogicalExtensionCodec> = (&ffi.logical_codec).into();
        let mut ffi = ffi.clone();
        ffi.logical_codec = codec_for(Arc::clone(&extension_codec), &task_ctx, runtime.clone());
        let inner: Arc<dyn TableProvider> = (&ffi).into();
        Self {
            inner,
            extension_codec,
            _task_ctx: task_ctx,
            runtime,
        }
    }

    /// The provider with its codec bound to `session`'s task context, and that
    /// task context. The codec refers to it weakly, so the caller must keep the
    /// returned task context alive while the provider is in use. A provider
    /// that turned out to be local to this library uses no codec and is
    /// returned as is.
    fn bound_for(
        &self,
        session: &dyn Session,
    ) -> (Arc<SessionTaskContext>, Arc<dyn TableProvider>) {
        let task_ctx = Arc::new(SessionTaskContext(session.task_ctx()));
        let Some(foreign) = self.inner.downcast_ref::<ForeignTableProvider>() else {
            return (task_ctx, Arc::clone(&self.inner));
        };
        let mut ffi = foreign.0.clone();
        ffi.logical_codec = codec_for(
            Arc::clone(&self.extension_codec),
            &task_ctx,
            self.runtime.clone(),
        );
        (task_ctx, Arc::new(ForeignTableProvider(ffi)))
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
        let (_task_ctx, provider) = self.bound_for(session);
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
        let (_task_ctx, provider) = self.bound_for(session);
        provider.insert_into(session, input, insert_op).await
    }
}
