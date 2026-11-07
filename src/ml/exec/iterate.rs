//! Physical operators for `Iterate` and `LoopState`.

use std::collections::HashSet;
use std::fmt::Formatter;
use std::sync::Arc;

use datafusion::arrow::array::{ArrayRef, AsArray, BooleanArray, RecordBatch, UInt64Array};
use datafusion::arrow::compute::{concat_batches, filter_record_batch};
use datafusion::arrow::datatypes::{Schema, SchemaRef};
use datafusion::arrow::row::{RowConverter, SortField};
use datafusion::common::tree_node::TreeNodeRecursion;
use datafusion::common::{exec_err, internal_err, Result};
use datafusion::execution::session_state::SessionState;
use datafusion::execution::{SendableRecordBatchStream, TaskContext};
use datafusion::logical_expr::LogicalPlan;
use datafusion::physical_expr::PhysicalExpr;
use datafusion::physical_plan::coop::make_cooperative;
use datafusion::physical_plan::memory::MemoryStream;
use datafusion::physical_plan::stream::RecordBatchStreamAdapter;
use datafusion::physical_plan::{
    collect, DisplayAs, DisplayFormatType, ExecutionPlan, PlanProperties,
};
use futures::stream;

use crate::ml::nodes::iterate::{ConvergenceSpec, LoopHandle, LoopValue};
use crate::utils::compute_properties;

fn read(handle: &LoopHandle) -> Result<Vec<RecordBatch>> {
    match handle.0.read() {
        Ok(value) => Ok(value.batches.clone()),
        Err(_) => exec_err!("ML loop value lock poisoned"),
    }
}

fn write(handle: &LoopHandle, batches: Vec<RecordBatch>) -> Result<()> {
    match handle.0.write() {
        Ok(mut value) => {
            *value = LoopValue { batches };
            Ok(())
        }
        Err(_) => exec_err!("ML loop value lock poisoned"),
    }
}

/// Leaf streaming the current loop value.
#[derive(Debug)]
pub(crate) struct LoopStateExec {
    handle: LoopHandle,
    schema: SchemaRef,
    cache: Arc<PlanProperties>,
}

impl LoopStateExec {
    pub(crate) fn new(handle: LoopHandle, schema: SchemaRef) -> Self {
        let cache = compute_properties(schema.clone());
        Self {
            handle,
            schema,
            cache,
        }
    }
}

impl DisplayAs for LoopStateExec {
    fn fmt_as(&self, _t: DisplayFormatType, f: &mut Formatter) -> std::fmt::Result {
        write!(f, "LoopStateExec")
    }
}

impl ExecutionPlan for LoopStateExec {
    fn name(&self) -> &str {
        "LoopStateExec"
    }

    fn apply_expressions(
        &self,
        _f: &mut dyn FnMut(&Arc<dyn PhysicalExpr>) -> Result<TreeNodeRecursion>,
    ) -> Result<TreeNodeRecursion> {
        Ok(TreeNodeRecursion::Continue)
    }

    fn schema(&self) -> SchemaRef {
        self.schema.clone()
    }

    fn properties(&self) -> &Arc<PlanProperties> {
        &self.cache
    }

    fn children(&self) -> Vec<&Arc<dyn ExecutionPlan>> {
        vec![]
    }

    fn with_new_children(
        self: Arc<Self>,
        _children: Vec<Arc<dyn ExecutionPlan>>,
    ) -> Result<Arc<dyn ExecutionPlan>> {
        Ok(self)
    }

    fn execute(
        &self,
        partition: usize,
        _context: Arc<TaskContext>,
    ) -> Result<SendableRecordBatchStream> {
        if partition != 0 {
            return internal_err!("LoopStateExec has one partition, asked for {partition}");
        }
        let batches = read(&self.handle)?;
        let stream = MemoryStream::try_new(batches, self.schema.clone(), None)?;
        Ok(make_cooperative(Box::pin(stream)))
    }
}

/// Runs `init` into the loop value, then plans and runs `body` once per
/// iteration (re-planned each time), upserting its output by `key`, until the
/// convergence column is true or `max_iter` iterations have run. Emits the
/// final loop value plus `n_iter`, as one partition.
///
/// Plans asynchronously with the `SessionState` the extension planner was
/// given; it never waits on the runtime or calls into Python.
#[derive(Debug)]
pub(crate) struct IterateExec {
    init: Arc<dyn ExecutionPlan>,
    body: LogicalPlan,
    key: Vec<String>,
    max_iter: usize,
    converged: ConvergenceSpec,
    handle: LoopHandle,
    state: SessionState,
    schema: SchemaRef,
    cache: Arc<PlanProperties>,
}

impl IterateExec {
    #[allow(clippy::too_many_arguments)]
    pub(crate) fn new(
        init: Arc<dyn ExecutionPlan>,
        body: LogicalPlan,
        key: Vec<String>,
        max_iter: usize,
        converged: ConvergenceSpec,
        handle: LoopHandle,
        state: SessionState,
        schema: SchemaRef,
    ) -> Self {
        let cache = compute_properties(schema.clone());
        Self {
            init,
            body,
            key,
            max_iter,
            converged,
            handle,
            state,
            schema,
            cache,
        }
    }
}

impl DisplayAs for IterateExec {
    fn fmt_as(&self, _t: DisplayFormatType, f: &mut Formatter) -> std::fmt::Result {
        write!(
            f,
            "IterateExec: key=[{}], max_iter={}",
            self.key.join(", "),
            self.max_iter
        )
    }
}

/// Indices of `columns` in `schema`.
fn indices(schema: &Schema, columns: &[String]) -> Result<Vec<usize>> {
    columns.iter().map(|c| Ok(schema.index_of(c)?)).collect()
}

/// `old` rows whose key is absent from `new`, followed by `new`.
fn upsert(
    schema: &SchemaRef,
    key: &[usize],
    old: &[RecordBatch],
    new: RecordBatch,
) -> Result<RecordBatch> {
    let fields = key
        .iter()
        .map(|&i| SortField::new(schema.field(i).data_type().clone()))
        .collect();
    let converter = RowConverter::new(fields)?;
    let key_columns = |batch: &RecordBatch| -> Vec<ArrayRef> {
        key.iter().map(|&i| batch.column(i).clone()).collect()
    };
    let new_rows = converter.convert_columns(&key_columns(&new))?;
    let new_keys: HashSet<_> = new_rows.iter().collect();
    let mut kept = Vec::with_capacity(old.len() + 1);
    for batch in old {
        let rows = converter.convert_columns(&key_columns(batch))?;
        let keep: BooleanArray = rows.iter().map(|r| Some(!new_keys.contains(&r))).collect();
        kept.push(filter_record_batch(batch, &keep)?);
    }
    kept.push(new);
    Ok(concat_batches(schema, &kept)?)
}

impl ExecutionPlan for IterateExec {
    fn name(&self) -> &str {
        "IterateExec"
    }

    fn apply_expressions(
        &self,
        _f: &mut dyn FnMut(&Arc<dyn PhysicalExpr>) -> Result<TreeNodeRecursion>,
    ) -> Result<TreeNodeRecursion> {
        Ok(TreeNodeRecursion::Continue)
    }

    fn schema(&self) -> SchemaRef {
        self.schema.clone()
    }

    fn properties(&self) -> &Arc<PlanProperties> {
        &self.cache
    }

    fn children(&self) -> Vec<&Arc<dyn ExecutionPlan>> {
        vec![&self.init]
    }

    fn with_new_children(
        self: Arc<Self>,
        children: Vec<Arc<dyn ExecutionPlan>>,
    ) -> Result<Arc<dyn ExecutionPlan>> {
        let [init]: [Arc<dyn ExecutionPlan>; 1] = match children.try_into() {
            Ok(children) => children,
            Err(children) => {
                return internal_err!("IterateExec takes 1 child, got {}", children.len())
            }
        };
        Ok(Arc::new(Self::new(
            init,
            self.body.clone(),
            self.key.clone(),
            self.max_iter,
            self.converged.clone(),
            self.handle.clone(),
            self.state.clone(),
            self.schema.clone(),
        )))
    }

    fn execute(
        &self,
        partition: usize,
        context: Arc<TaskContext>,
    ) -> Result<SendableRecordBatchStream> {
        if partition != 0 {
            return internal_err!("IterateExec has one partition, asked for {partition}");
        }
        let init = Arc::clone(&self.init);
        let body = self.body.clone();
        let max_iter = self.max_iter;
        let ConvergenceSpec::Column(flag) = self.converged.clone();
        let handle = self.handle.clone();
        let state = self.state.clone();
        let output_schema = self.schema.clone();
        let value_schema = init.schema();
        let key = indices(&value_schema, &self.key)?;
        let run = async move {
            let initial = collect(init, Arc::clone(&context)).await?;
            write(&handle, vec![concat_batches(&value_schema, &initial)?])?;
            let mut n_iter = 0;
            for i in 1..=max_iter {
                // Hand the worker back between iterations.
                tokio::task::yield_now().await;
                let plan = state.create_physical_plan(&body).await?;
                let output =
                    concat_batches(&plan.schema(), &collect(plan, Arc::clone(&context)).await?)?;
                let flag_index = output.schema().index_of(&flag)?;
                let converged = output.column(flag_index).as_boolean().true_count() > 0;
                let mut new = output;
                new.remove_column(flag_index);
                let new = RecordBatch::try_new(value_schema.clone(), new.columns().to_vec())?;
                let value = upsert(&value_schema, &key, &read(&handle)?, new)?;
                write(&handle, vec![value])?;
                n_iter = i;
                if converged {
                    break;
                }
            }
            let [value]: [RecordBatch; 1] = match read(&handle)?.try_into() {
                Ok(value) => value,
                Err(_) => return internal_err!("ML loop value must be one batch"),
            };
            let mut columns = value.columns().to_vec();
            columns.push(Arc::new(UInt64Array::from(vec![
                n_iter as u64;
                value.num_rows()
            ])));
            Ok(RecordBatch::try_new(output_schema, columns)?)
        };
        Ok(Box::pin(RecordBatchStreamAdapter::new(
            self.schema.clone(),
            stream::once(run),
        )))
    }
}
