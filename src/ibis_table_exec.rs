use std::any::Any;
use std::fmt::Formatter;
use std::sync::Arc;

use arrow::array::RecordBatch;
use arrow::datatypes::SchemaRef;
use arrow::pyarrow::PyArrowType;
use datafusion::execution::{SendableRecordBatchStream, TaskContext};
use datafusion::physical_plan::stream::RecordBatchStreamAdapter;
use datafusion::physical_plan::{DisplayAs, DisplayFormatType, ExecutionPlan, PlanProperties};
use datafusion_common::project_schema;
use datafusion_common::DataFusionError as InnerDataFusionError;
use futures::stream;
use pyo3::types::PyIterator;
use pyo3::{Bound, Py, PyAny, Python};

use crate::errors::DataFusionError;
use crate::utils::compute_properties;

use pyo3::prelude::*;

/// Batches buffered in the channel between the blocking reader thread and the
/// async stream consumer.  Limits memory while allowing the reader to stay one
/// step ahead of the consumer.
const CHANNEL_CAPACITY: usize = 8;

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

        let (tx, rx) = tokio::sync::mpsc::channel(CHANNEL_CAPACITY);

        // One blocking thread owns the Python reader for the entire stream
        // lifetime and drains it batch-by-batch. Running the pull on the blocking
        // pool (never an async worker) is what keeps re-entrant providers safe:
        // when this reader is a Python `scan()` generator that itself re-enters
        // `execute_stream`, the nested block_on lands on a blocking thread and the
        // inner query still finds a free worker, so a chain deeper than the worker
        // count cannot starve the runtime. The GIL is acquired and released once
        // per batch, before blocking_send, so other Python threads can run while
        // the async consumer catches up.
        tokio::task::spawn_blocking(move || {
            let iter = match Python::attach(|py| {
                PyIterator::from_object(record_batch_reader.bind(py)).map(|it| it.unbind())
            }) {
                Ok(it) => it,
                Err(e) => {
                    let _ = tx.blocking_send(Err(InnerDataFusionError::External(Box::new(e))));
                    return;
                }
            };

            loop {
                // GIL released when the Python::attach closure returns, before
                // blocking_send. A re-entrant reader releases it again internally
                // (via wait_for_future's py.detach) while it drains its own nested
                // stream, so the nested runtime work never holds the GIL here.
                let next = Python::attach(|py| {
                    let mut bound_iter = iter.clone_ref(py).into_bound(py);
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
                });

                match next {
                    None => break,
                    Some(Err(e)) => {
                        let _ = tx.blocking_send(Err(e));
                        break;
                    }
                    Some(Ok(rb)) => {
                        if tx.blocking_send(Ok(rb)).is_err() {
                            break; // receiver dropped — query cancelled
                        }
                    }
                }
            }
        });

        let stream = stream::unfold(rx, |mut rx| async move {
            rx.recv().await.map(|item| (item, rx))
        });

        Ok(Box::pin(RecordBatchStreamAdapter::new(schema, stream)))
    }
}
