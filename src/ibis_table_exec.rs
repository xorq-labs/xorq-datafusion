use std::fmt::Formatter;
use std::sync::Arc;

use arrow::array::RecordBatch;
use arrow::datatypes::SchemaRef;
use arrow::pyarrow::PyArrowType;
use datafusion::common::tree_node::TreeNodeRecursion;
use datafusion::execution::{SendableRecordBatchStream, TaskContext};
use datafusion::physical_expr::PhysicalExpr;
use datafusion::physical_plan::{DisplayAs, DisplayFormatType, ExecutionPlan, PlanProperties};
use datafusion_common::project_schema;
use datafusion_common::DataFusionError as InnerDataFusionError;
use pyo3::types::PyIterator;
use pyo3::{Bound, Py, PyAny, Python};

use crate::errors::DataFusionError;
use crate::utils::compute_properties;

use pyo3::prelude::*;

#[derive(Debug)]
pub struct IbisTableExec {
    /// `Arc` so `execute()` can hand a reference to the pull closure without
    /// touching the GIL (see the comment there).
    record_batch_reader: Arc<Py<PyAny>>,
    schema: SchemaRef,
    /// Column indices to keep, applied to each batch in Rust.
    projection: Option<Vec<usize>>,
    cache: Arc<PlanProperties>,
}

impl IbisTableExec {
    pub(crate) fn new(
        _py: Python,
        record_batch_reader: &Bound<'_, PyAny>,
        projections: Option<&Vec<usize>>,
    ) -> Result<Self, DataFusionError> {
        let schema: SchemaRef = Arc::new(
            record_batch_reader
                .getattr("schema")?
                .extract::<PyArrowType<_>>()?
                .0,
        );
        let schema = project_schema(&schema, projections)?;

        let cache = compute_properties(schema.clone());

        Ok(IbisTableExec {
            record_batch_reader: Arc::new(record_batch_reader.clone().unbind()),
            schema,
            projection: projections.cloned(),
            cache,
        })
    }
}

impl DisplayAs for IbisTableExec {
    fn fmt_as(&self, _t: DisplayFormatType, f: &mut Formatter) -> std::fmt::Result {
        write!(f, "IbisTableExec")
    }
}

impl ExecutionPlan for IbisTableExec {
    fn name(&self) -> &str {
        "ibis_table"
    }

    fn apply_expressions(
        &self,
        _f: &mut dyn FnMut(&Arc<dyn PhysicalExpr>) -> datafusion_common::Result<TreeNodeRecursion>,
    ) -> datafusion_common::Result<TreeNodeRecursion> {
        // Holds no `PhysicalExpr`s to visit.
        Ok(TreeNodeRecursion::Continue)
    }

    fn schema(&self) -> SchemaRef {
        self.schema.clone()
    }

    fn properties(&self) -> &Arc<PlanProperties> {
        &self.cache
    }

    fn children(&self) -> Vec<&Arc<dyn ExecutionPlan>> {
        // this is a leaf node and has no children
        vec![]
    }

    fn with_new_children(
        self: Arc<Self>,
        _children: Vec<Arc<dyn ExecutionPlan>>,
    ) -> datafusion_common::Result<Arc<dyn ExecutionPlan>> {
        Ok(self)
    }

    fn execute(
        &self,
        _partition: usize,
        _context: Arc<TaskContext>,
    ) -> datafusion_common::Result<SendableRecordBatchStream> {
        let schema = self.schema.clone();
        let projection = self.projection.clone();
        // Arc clone -- no GIL: execute() runs on whatever thread the parent plan
        // polls from, which is frequently an async worker.
        let record_batch_reader = Arc::clone(&self.record_batch_reader);

        // The pull closure runs on the blocking pool (see spawn_channel_stream), so
        // it may hold the GIL. The Python iterator is built lazily on the first pull
        // rather than here, so GIL acquisition never lands on an async worker. A
        // re-entrant reader (a Python `scan()` generator that drains a nested
        // execute_stream) releases the GIL again internally via wait_for_future's
        // py.detach, so nested runtime work never holds the GIL here.
        let mut iter: Option<Py<PyIterator>> = None;
        let pull: crate::utils::BatchPull = Box::new(move || {
            // Each batch is imported with its *own* schema (`__arrow_c_array__`
            // carries schema + array), so a batch that contradicts the declared
            // schema is caught by spawn_channel_stream's check instead of being
            // reinterpreted under the declared types. That is why this path keeps
            // the Python iterator rather than moving to `__arrow_c_stream__`, whose
            // ABI sends the schema once and bare arrays after: there, a reader that
            // declares `utf8` and yields `large_utf8` silently corrupts the scan.
            let pulled = Python::attach(|py| {
                if iter.is_none() {
                    // Built once per stream, not rebuilt for every batch.
                    match PyIterator::from_object(record_batch_reader.bind(py)) {
                        Ok(built) => iter = Some(built.unbind()),
                        Err(e) => return Some(Err(InnerDataFusionError::External(Box::new(e)))),
                    }
                }
                let mut bound_iter = iter
                    .as_ref()
                    .expect("initialized above")
                    .clone_ref(py)
                    .into_bound(py);
                bound_iter.next().map(|res| {
                    res.and_then(|batch| Ok(batch.extract::<PyArrowType<RecordBatch>>()?.0))
                        .map_err(|e: PyErr| InnerDataFusionError::External(Box::new(e)))
                })
            });

            // Projected in Rust, with the GIL already released: `select` on the
            // Python batch cost a method call and an intermediate pyarrow object
            // per batch, and both are pure overhead next to `RecordBatch::project`.
            match (pulled, &projection) {
                (Some(Ok(batch)), Some(indices)) => {
                    Some(batch.project(indices).map_err(InnerDataFusionError::from))
                }
                (pulled, _) => pulled,
            }
        });

        // Arbitrary user Python: pull only what the query polls for, so a reader
        // that blocks on a batch beyond a LIMIT never strands a pool thread.
        Ok(crate::utils::spawn_channel_stream(
            schema,
            pull,
            crate::utils::ReadAhead::OnDemand,
        ))
    }
}
