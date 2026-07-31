use std::any::Any;
use std::fmt::Formatter;
use std::sync::Arc;

use arrow::array::RecordBatch;
use arrow::datatypes::SchemaRef;
use arrow::pyarrow::PyArrowType;
use datafusion::execution::{SendableRecordBatchStream, TaskContext};
use datafusion::physical_plan::{DisplayAs, DisplayFormatType, ExecutionPlan, PlanProperties};
use datafusion_common::project_schema;
use datafusion_common::DataFusionError as InnerDataFusionError;
use pyo3::types::{PyIterator, PyList};
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
    columns: Option<Vec<String>>,
    cache: Arc<PlanProperties>,
}

impl IbisTableExec {
    pub(crate) fn new(
        _py: Python,
        record_batch_reader: &Bound<'_, PyAny>,
        projections: Option<&Vec<usize>>,
    ) -> Result<Self, DataFusionError> {
        // TODO use indices instead of columns
        let columns: Option<Result<Vec<String>, DataFusionError>> = projections.map(|p| {
            p.iter()
                .map(|index| {
                    let name: String = record_batch_reader
                        .getattr("schema")?
                        .call_method1("field", (*index,))?
                        .getattr("name")?
                        .extract()?;
                    Ok(name)
                })
                .collect()
        });
        let columns: Option<Vec<String>> = columns.transpose()?;

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
            columns,
            cache,
        })
    }
}

/// Per-stream Python state, built on the first pull (on the blocking pool) and
/// reused for every batch of that stream.
struct PullState {
    iter: Py<PyIterator>,
    /// The projection as a Python list, converted once instead of per batch.
    projection: Option<Py<PyList>>,
}

impl PullState {
    fn new(
        py: Python,
        record_batch_reader: &Py<PyAny>,
        columns: Option<&[String]>,
    ) -> PyResult<Self> {
        let iter = PyIterator::from_object(record_batch_reader.bind(py))?.unbind();
        let projection = columns
            .map(|cols| PyList::new(py, cols).map(|list| list.unbind()))
            .transpose()?;
        Ok(Self { iter, projection })
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

    fn as_any(&self) -> &dyn Any {
        self
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
        let columns = self.columns.clone();
        // Arc clone -- no GIL: execute() runs on whatever thread the parent plan
        // polls from, which is frequently an async worker.
        let record_batch_reader = Arc::clone(&self.record_batch_reader);

        // The pull closure runs on the blocking pool (see spawn_channel_stream), so
        // it may hold the GIL. The Python iterator and the projection list are both
        // built lazily on the first pull rather than here, so GIL acquisition never
        // lands on an async worker. A re-entrant reader (a Python `scan()`
        // generator that drains a nested execute_stream) releases the GIL again
        // internally via wait_for_future's py.detach, so nested runtime work never
        // holds the GIL here.
        let mut state: Option<PullState> = None;
        let pull: crate::utils::BatchPull = Box::new(move || {
            Python::attach(|py| {
                if state.is_none() {
                    // Iterator and projection list are built once per stream, not
                    // rebuilt for every batch.
                    match PullState::new(py, &record_batch_reader, columns.as_deref()) {
                        Ok(built) => state = Some(built),
                        Err(e) => return Some(Err(InnerDataFusionError::External(Box::new(e)))),
                    }
                }
                let state = state.as_ref().expect("initialized above");
                let mut bound_iter = state.iter.clone_ref(py).into_bound(py);
                bound_iter.next().map(|res| {
                    res.and_then(|batch| {
                        let batch = match &state.projection {
                            Some(cols) => batch.call_method1("select", (cols.bind(py),))?,
                            None => batch,
                        };
                        Ok(batch.extract::<PyArrowType<RecordBatch>>()?.0)
                    })
                    .map_err(|e: PyErr| InnerDataFusionError::External(Box::new(e)))
                })
            })
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
