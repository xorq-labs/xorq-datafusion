use std::any::Any;
use std::sync::Arc;

use async_trait::async_trait;
use datafusion::arrow::datatypes::SchemaRef;
use datafusion::arrow::ffi_stream::ArrowArrayStreamReader;
use datafusion::arrow::pyarrow::PyArrowType;
use datafusion::catalog::streaming::StreamingTable;
use datafusion::catalog::Session;
use datafusion::datasource::{TableProvider, TableType};
use datafusion::error::Result;
use datafusion::execution::TaskContext;
use datafusion::physical_plan::streaming::PartitionStream;
use datafusion::physical_plan::{ExecutionPlan, SendableRecordBatchStream};
use datafusion_common::DataFusionError;
use datafusion_expr::{Expr, SortExpr};
use pyo3::prelude::*;

/// A [`TableProvider`] backed by a Python object that supports the Arrow C stream
/// interface (`__arrow_c_stream__`).
///
/// Planning, projection, limit and sort-order handling are delegated to
/// DataFusion's [`StreamingTable`]; this type only supplies the partition stream
/// and keeps the table reported as [`TableType::Base`] (a bare `StreamingTable`
/// reports itself as a view).
///
/// The Python object is held by reference and re-queried on every `execute()` call,
/// so tables that support multiple calls to `__arrow_c_stream__` (e.g. `pyarrow.Table`)
/// can be scanned more than once.  Single-use readers (e.g. `pyarrow.RecordBatchReader`)
/// will raise a Python error on the second call, which surfaces as a `DataFusionError`
/// rather than silently returning empty results.
#[derive(Debug)]
pub struct PyRecordBatchProvider {
    inner: StreamingTable,
}

impl PyRecordBatchProvider {
    pub fn try_new(
        py_object: Py<PyAny>,
        schema: SchemaRef,
        sort_order: Vec<SortExpr>,
    ) -> Result<Self> {
        let partition = Arc::new(PyArrowStreamPartition {
            py_object: Arc::new(py_object),
            schema: Arc::clone(&schema),
        });
        let inner = StreamingTable::try_new(schema, vec![partition])?.with_sort_order(sort_order);
        Ok(Self { inner })
    }
}

#[async_trait]
impl TableProvider for PyRecordBatchProvider {
    fn as_any(&self) -> &dyn Any {
        self
    }

    fn schema(&self) -> SchemaRef {
        self.inner.schema()
    }

    fn table_type(&self) -> TableType {
        TableType::Base
    }

    async fn scan(
        &self,
        state: &dyn Session,
        projection: Option<&Vec<usize>>,
        filters: &[Expr],
        limit: Option<usize>,
    ) -> Result<Arc<dyn ExecutionPlan>> {
        self.inner.scan(state, projection, filters, limit).await
    }
}

/// The single partition of a [`PyRecordBatchProvider`]: one Arrow C stream read
/// from the Python object per `execute()`.
#[derive(Debug)]
struct PyArrowStreamPartition {
    py_object: Arc<Py<PyAny>>,
    schema: SchemaRef,
}

impl PartitionStream for PyArrowStreamPartition {
    fn schema(&self) -> &SchemaRef {
        &self.schema
    }

    fn execute(&self, _ctx: Arc<TaskContext>) -> SendableRecordBatchStream {
        // Arc clone -- no GIL: execute() runs on whatever thread the parent plan
        // polls from, which is frequently an async worker.
        let py_object = Arc::clone(&self.py_object);

        // The pull runs on the blocking pool (see spawn_channel_stream). The reader
        // is acquired lazily on the first pull, and each batch is produced there,
        // so an idle/abandoned stream pins no blocking thread.
        let mut reader: Option<ArrowArrayStreamReader> = None;
        let pull: crate::utils::BatchPull = Box::new(move || {
            if reader.is_none() {
                // Acquire the Arrow C stream reader once, on the blocking pool.
                match Python::attach(|py| {
                    py_object
                        .bind(py)
                        .extract::<PyArrowType<ArrowArrayStreamReader>>()
                        .map(|t| t.0)
                        .map_err(|e| DataFusionError::External(Box::new(e)))
                }) {
                    Ok(r) => reader = Some(r),
                    Err(e) => return Some(Err(e)),
                }
            }

            // Do NOT hold the GIL across next(): the Arrow C get_next callback
            // acquires the GIL itself; holding it here while another reader thread
            // owns the shared-cache Rust mutex is the GIL+mutex inversion (two
            // scans sharing one upstream cache, e.g. batchcorder StreamCache).
            //
            // Batches go out unprojected; StreamingTableExec projects them.
            reader
                .as_mut()
                .expect("initialized above")
                .next()
                .map(|res| res.map_err(DataFusionError::from))
        });

        // Read-ahead here matches what this path always did; the speculation budget
        // caps what a reader that blocks on a batch nobody asked for can cost.
        crate::utils::spawn_channel_stream(
            Arc::clone(&self.schema),
            pull,
            crate::utils::ReadAhead::Buffered,
        )
    }
}
