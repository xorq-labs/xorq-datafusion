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
use pyo3::types::PyIterator;
use pyo3::{Bound, Py, PyAny, Python};

use crate::errors::DataFusionError;
use crate::utils::compute_properties;

use pyo3::prelude::*;

#[derive(Debug)]
pub struct IbisTableExec {
    record_batch_reader: Py<PyAny>,
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
            record_batch_reader: record_batch_reader.clone().unbind(),
            schema,
            columns,
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
        let record_batch_reader = Python::attach(|py| self.record_batch_reader.clone_ref(py));

        // The pull closure runs on the blocking pool (see spawn_channel_stream), so
        // it may hold the GIL. The Python iterator is built lazily on the first
        // pull rather than here, so GIL acquisition never lands on an async worker.
        // A re-entrant reader (a Python `scan()` generator that drains a nested
        // execute_stream) releases the GIL again internally via wait_for_future's
        // py.detach, so nested runtime work never holds the GIL here.
        let mut iter: Option<Py<PyIterator>> = None;
        let pull: crate::utils::BatchPull = Box::new(move || {
            Python::attach(|py| {
                if iter.is_none() {
                    match PyIterator::from_object(record_batch_reader.bind(py)) {
                        Ok(it) => iter = Some(it.unbind()),
                        Err(e) => return Some(Err(InnerDataFusionError::External(Box::new(e)))),
                    }
                }
                let mut bound_iter = iter.as_ref().unwrap().clone_ref(py).into_bound(py);
                bound_iter.next().map(|res| {
                    res.and_then(|batch| {
                        let batch = match &columns {
                            Some(cols) => batch.call_method1("select", (cols.clone(),))?,
                            None => batch,
                        };
                        Ok(batch.extract::<PyArrowType<RecordBatch>>()?.0)
                    })
                    .map_err(|e: PyErr| InnerDataFusionError::External(Box::new(e)))
                })
            })
        });

        Ok(crate::utils::spawn_channel_stream(schema, pull))
    }
}
