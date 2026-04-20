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
use datafusion::physical_plan::stream::RecordBatchStreamAdapter;
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

    /// Acquire a fresh stream from Python and return it as a lazy async stream.
    ///
    /// Each batch is fetched inside `spawn_blocking` so that the Arrow C-callback
    /// invocations (which may need the GIL) never block the Tokio executor thread.
    /// Only one batch is in flight at a time; the full dataset is never materialised.
    fn execute(
        &self,
        _partition: usize,
        _context: Arc<TaskContext>,
    ) -> Result<SendableRecordBatchStream> {
        let projections = self.projections.clone();
        let projected_schema = self.projected_schema.clone();

        let reader = Python::attach(|py| {
            self.record_batch_provider
                .py_object
                .bind(py)
                .extract::<PyArrowType<ArrowArrayStreamReader>>()
                .map(|t| t.0)
                .map_err(|e| DataFusionError::External(Box::new(e)))
        })?;

        // Drive the sync reader one batch at a time from a blocking thread so we
        // never stall the async executor.  The reader is moved into the unfold state
        // and is held for the lifetime of the stream.
        let stream = futures::stream::unfold(Some(reader), move |state| {
            let projections = projections.clone();
            async move {
                let mut reader = state?;
                let result = tokio::task::spawn_blocking(move || {
                    // Acquire the GIL for each batch: the C callbacks registered by
                    // PyArrow may call back into Python for non-in-memory sources.
                    let batch = Python::attach(|_py| reader.next());
                    (batch, reader)
                })
                .await;

                match result {
                    Ok((None, _)) => None,
                    Ok((Some(batch_result), reader)) => {
                        let item = batch_result.map_err(DataFusionError::from).and_then(|rb| {
                            match &projections {
                                Some(pj) => {
                                    rb.project(pj.as_slice()).map_err(DataFusionError::from)
                                }
                                None => Ok(rb),
                            }
                        });
                        Some((item, Some(reader)))
                    }
                    Err(join_err) => {
                        Some((Err(DataFusionError::External(Box::new(join_err))), None))
                    }
                }
            }
        });

        Ok(Box::pin(RecordBatchStreamAdapter::new(
            projected_schema,
            stream,
        )))
    }
}
