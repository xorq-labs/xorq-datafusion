use std::any::Any;
use std::fmt;
use std::sync::Arc;

use crate::utils::compute_properties_with_orderings;
use async_trait::async_trait;
use datafusion::arrow::datatypes::SchemaRef;
use datafusion::arrow::ffi_stream::ArrowArrayStreamReader;
use datafusion::arrow::pyarrow::PyArrowType;
use datafusion::catalog::Session;
use datafusion::datasource::{TableProvider, TableType};
use datafusion::error::Result;
use datafusion::execution::TaskContext;
use datafusion::physical_expr::LexOrdering;
use datafusion::physical_plan::{
    project_schema, DisplayAs, DisplayFormatType, ExecutionPlan, PlanProperties,
    SendableRecordBatchStream,
};
use datafusion_common::DataFusionError;
use datafusion_expr::Expr;
use pyo3::prelude::*;

/// A [`TableProvider`] backed by a Python object that supports the Arrow C stream
/// interface (`__arrow_c_stream__`).
///
/// The Python object is held by reference and re-queried on every `execute()` call,
/// so tables that support multiple calls to `__arrow_c_stream__` (e.g. `pyarrow.Table`)
/// can be scanned more than once.  Single-use readers (e.g. `pyarrow.RecordBatchReader`)
/// will raise a Python error on the second call, which surfaces as a `DataFusionError`
/// rather than silently returning empty results.
#[derive(Clone, Debug)]
pub struct PyRecordBatchProvider {
    py_object: Arc<Py<PyAny>>,
    schema: SchemaRef,
    ordering: Option<LexOrdering>,
}

impl PyRecordBatchProvider {
    pub fn new(py_object: Py<PyAny>, schema: SchemaRef, ordering: Option<LexOrdering>) -> Self {
        Self {
            py_object: Arc::new(py_object),
            schema,
            ordering,
        }
    }

    pub(crate) async fn create_physical_plan(
        &self,
        projections: Option<&Vec<usize>>,
        schema: SchemaRef,
    ) -> Result<Arc<dyn ExecutionPlan>> {
        Ok(Arc::new(PyRecordBatchProviderExec::new(
            self.clone(),
            projections,
            schema,
        )))
    }
}

#[async_trait]
impl TableProvider for PyRecordBatchProvider {
    fn as_any(&self) -> &dyn Any {
        self
    }

    fn schema(&self) -> SchemaRef {
        self.schema.clone()
    }

    fn table_type(&self) -> TableType {
        TableType::Base
    }

    async fn scan(
        &self,
        _state: &dyn Session,
        projection: Option<&Vec<usize>>,
        _filter: &[Expr],
        _limit: Option<usize>,
    ) -> Result<Arc<dyn ExecutionPlan>> {
        self.create_physical_plan(projection, self.schema()).await
    }
}

#[derive(Debug, Clone)]
struct PyRecordBatchProviderExec {
    record_batch_provider: PyRecordBatchProvider,
    projected_schema: SchemaRef,
    projections: Option<Vec<usize>>,
    plan_properties: Arc<PlanProperties>,
}

impl PyRecordBatchProviderExec {
    fn new(
        record_batch_provider: PyRecordBatchProvider,
        projections: Option<&Vec<usize>>,
        schema: SchemaRef,
    ) -> Self {
        let projected_schema = project_schema(&schema, projections).unwrap();
        let projections = projections.map(|v| (*v).clone());
        let orderings = if let Some(ordering) = &record_batch_provider.ordering {
            vec![ordering.clone()]
        } else {
            vec![]
        };
        let plan_properties =
            compute_properties_with_orderings(projected_schema.clone(), &orderings);
        Self {
            record_batch_provider,
            projected_schema,
            projections,
            plan_properties,
        }
    }
}

impl DisplayAs for PyRecordBatchProviderExec {
    fn fmt_as(&self, _t: DisplayFormatType, f: &mut fmt::Formatter) -> std::fmt::Result {
        if let Some(output_ordering) = self.plan_properties.output_ordering() {
            write!(f, "PyRecordBatchProviderExec ordering=[{output_ordering}]")
        } else {
            write!(f, "PyRecordBatchProviderExec ordering=[None]")
        }
    }
}

impl ExecutionPlan for PyRecordBatchProviderExec {
    fn name(&self) -> &str {
        "py_record_batch_provider"
    }

    fn as_any(&self) -> &dyn Any {
        self
    }

    fn schema(&self) -> SchemaRef {
        self.projected_schema.clone()
    }

    fn properties(&self) -> &Arc<PlanProperties> {
        &self.plan_properties
    }

    fn maintains_input_order(&self) -> Vec<bool> {
        vec![]
    }

    fn children(&self) -> Vec<&Arc<dyn ExecutionPlan>> {
        vec![]
    }

    fn with_new_children(
        self: Arc<Self>,
        _: Vec<Arc<dyn ExecutionPlan>>,
    ) -> Result<Arc<dyn ExecutionPlan>> {
        Ok(self)
    }

    fn execute(
        &self,
        _partition: usize,
        _context: Arc<TaskContext>,
    ) -> Result<SendableRecordBatchStream> {
        let projections = self.projections.clone();
        let projected_schema = self.projected_schema.clone();
        let py_object = self.record_batch_provider.py_object.clone();

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
            match reader.as_mut().unwrap().next() {
                None => None,
                Some(Err(e)) => Some(Err(DataFusionError::from(e))),
                Some(Ok(rb)) => Some(match &projections {
                    Some(pj) => rb.project(pj.as_slice()).map_err(DataFusionError::from),
                    None => Ok(rb),
                }),
            }
        });

        Ok(crate::utils::spawn_channel_stream(projected_schema, pull))
    }
}
