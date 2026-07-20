/// Implements a Datafusion physical ExecutionPlan that delegates to a PyArrow Dataset
/// This actually performs the projection, filtering and scanning of a Dataset
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyIterator, PyList};

use std::any::Any;
use std::sync::Arc;

use crate::errors::DataFusionError;
use crate::pyarrow_filter_expression::PyArrowFilterExpression;
use datafusion::arrow::datatypes::SchemaRef;
use datafusion::arrow::pyarrow::PyArrowType;
use datafusion::arrow::record_batch::RecordBatch;
use datafusion::error::{DataFusionError as InnerDataFusionError, Result as DFResult};
use datafusion::execution::context::TaskContext;
use datafusion::logical_expr::utils::conjunction;
use datafusion::logical_expr::Expr;
use datafusion::physical_expr::EquivalenceProperties;
use datafusion::physical_plan::execution_plan::{Boundedness, EmissionType};
use datafusion::physical_plan::{
    DisplayAs, DisplayFormatType, ExecutionPlan, Partitioning, SendableRecordBatchStream,
};

// Wraps a pyarrow.dataset.Dataset class and implements a Datafusion ExecutionPlan around it
#[derive(Debug)]
pub(crate) struct DatasetExec {
    // Wrapped in Arc so execute() can clone without acquiring the GIL.
    dataset: Arc<Py<PyAny>>,
    schema: SchemaRef,
    fragments: Arc<Py<PyList>>,
    columns: Option<Vec<String>>,
    filter_expr: Option<Arc<Py<PyAny>>>,
    plan_properties: Arc<datafusion::physical_plan::PlanProperties>,
}

impl DatasetExec {
    pub fn new(
        py: Python,
        dataset: &Bound<'_, PyAny>,
        projection: Option<Vec<usize>>,
        filters: &[Expr],
    ) -> Result<Self, DataFusionError> {
        let columns: Option<Result<Vec<String>, DataFusionError>> = projection.map(|p| {
            p.iter()
                .map(|index| {
                    let name: String = dataset
                        .getattr("schema")?
                        .call_method1("field", (*index,))?
                        .getattr("name")?
                        .extract()?;
                    Ok(name)
                })
                .collect()
        });
        let columns: Option<Vec<String>> = columns.transpose()?;
        let filter_expr: Option<Py<PyAny>> = conjunction(filters.to_owned())
            .map(|filters| {
                PyArrowFilterExpression::try_from(&filters)
                    .map(|filter_expr| filter_expr.inner().clone_ref(py))
            })
            .transpose()?;

        let kwargs = PyDict::new(py);

        kwargs.set_item("columns", columns.clone())?;
        kwargs.set_item(
            "filter",
            filter_expr.as_ref().map(|expr| expr.clone_ref(py)),
        )?;

        let scanner = dataset.call_method("scanner", (), Some(&kwargs))?;

        let schema: SchemaRef = Arc::new(
            scanner
                .getattr("projected_schema")?
                .extract::<PyArrowType<_>>()?
                .0,
        );

        let builtins = Python::import(py, "builtins")?;
        let pylist = builtins.getattr("list")?;

        // Get the fragments or partitions of the dataset
        let fragments_iterator: Bound<'_, PyAny> = dataset.call_method1(
            "get_fragments",
            (filter_expr.as_ref().map(|expr| expr.clone_ref(py)),),
        )?;

        let fragments_iter = pylist.call1((fragments_iterator,))?;
        let fragments = fragments_iter.cast::<PyList>().map_err(PyErr::from)?;

        let plan_properties = Arc::new(datafusion::physical_plan::PlanProperties::new(
            EquivalenceProperties::new(schema.clone()),
            Partitioning::UnknownPartitioning(fragments.len()),
            EmissionType::Incremental,
            Boundedness::Bounded,
        ));

        Ok(DatasetExec {
            dataset: Arc::new(dataset.clone().unbind()),
            schema,
            fragments: Arc::new(fragments.clone().unbind()),
            columns,
            filter_expr: filter_expr.map(Arc::new),
            plan_properties,
        })
    }
}

impl ExecutionPlan for DatasetExec {
    fn name(&self) -> &str {
        Self::static_name()
    }

    fn as_any(&self) -> &dyn Any {
        self
    }

    fn schema(&self) -> SchemaRef {
        self.schema.clone()
    }

    fn properties(&self) -> &Arc<datafusion::physical_plan::PlanProperties> {
        &self.plan_properties
    }

    fn children(&self) -> Vec<&Arc<dyn ExecutionPlan>> {
        vec![]
    }

    fn with_new_children(
        self: Arc<Self>,
        _: Vec<Arc<dyn ExecutionPlan>>,
    ) -> DFResult<Arc<dyn ExecutionPlan>> {
        Ok(self)
    }

    fn execute(
        &self,
        partition: usize,
        context: Arc<TaskContext>,
    ) -> DFResult<SendableRecordBatchStream> {
        let batch_size = context.session_config().batch_size();
        // Arc clones — no GIL needed.
        let dataset = self.dataset.clone();
        let fragments = self.fragments.clone();
        // Init-only captures: taken on the first pull when the scanner is built.
        let mut filter_expr = self.filter_expr.clone();
        let mut columns = self.columns.clone();
        let schema = self.schema.clone();

        // The pull runs on the blocking pool (see spawn_channel_stream). The pyarrow
        // scanner iterator is built lazily on the first pull, and each batch is
        // produced there, so an idle/abandoned stream pins no blocking thread.
        let mut iter: Option<Py<PyIterator>> = None;
        let pull: crate::utils::BatchPull = Box::new(move || {
            if iter.is_none() {
                let built = Python::attach(|py| -> Result<Py<PyIterator>, InnerDataFusionError> {
                    let fragment = fragments
                        .bind(py)
                        .get_item(partition)
                        .map_err(|e| InnerDataFusionError::External(Box::new(e)))?;
                    let dataset_schema = dataset
                        .bind(py)
                        .getattr("schema")
                        .map_err(|e| InnerDataFusionError::External(Box::new(e)))?;
                    let kwargs = PyDict::new(py);
                    kwargs
                        .set_item("columns", columns.take())
                        .map_err(|e| InnerDataFusionError::External(Box::new(e)))?;
                    kwargs
                        .set_item("filter", filter_expr.take().as_deref().map(|e| e.bind(py)))
                        .map_err(|e| InnerDataFusionError::External(Box::new(e)))?;
                    kwargs
                        .set_item("batch_size", batch_size)
                        .map_err(|e| InnerDataFusionError::External(Box::new(e)))?;
                    let scanner = fragment
                        .call_method("scanner", (dataset_schema,), Some(&kwargs))
                        .map_err(|e| InnerDataFusionError::External(Box::new(e)))?;
                    scanner
                        .call_method0("to_batches")
                        .and_then(|it| it.try_iter())
                        .map(|it| it.unbind())
                        .map_err(|e| InnerDataFusionError::External(Box::new(e)))
                });
                match built {
                    Ok(it) => iter = Some(it),
                    Err(e) => return Some(Err(e)),
                }
            }

            // GIL released when the Python::attach closure returns.
            Python::attach(|py| {
                let mut bound_iter = iter.as_ref().unwrap().clone_ref(py).into_bound(py);
                bound_iter.next().map(|r| {
                    r.and_then(|batch| Ok(batch.extract::<PyArrowType<RecordBatch>>()?.0))
                        .map_err(|e: PyErr| InnerDataFusionError::External(Box::new(e)))
                })
            })
        });

        Ok(crate::utils::spawn_channel_stream(schema, pull))
    }
}

impl DisplayAs for DatasetExec {
    fn fmt_as(&self, t: DisplayFormatType, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        Python::attach(|py| {
            let number_of_fragments = self.fragments.bind(py).len();
            match t {
                DisplayFormatType::Default
                | DisplayFormatType::Verbose
                | DisplayFormatType::TreeRender => {
                    let projected_columns: Vec<String> = self
                        .schema
                        .fields()
                        .iter()
                        .map(|x| x.name().to_owned())
                        .collect();
                    if let Some(filter_expr) = &self.filter_expr {
                        let filter_expr = filter_expr.bind(py).str().or(Err(std::fmt::Error))?;
                        write!(
                            f,
                            "DatasetExec: number_of_fragments={}, filter_expr={}, projection=[{}]",
                            number_of_fragments,
                            filter_expr,
                            projected_columns.join(", "),
                        )
                    } else {
                        write!(
                            f,
                            "DatasetExec: number_of_fragments={}, projection=[{}]",
                            number_of_fragments,
                            projected_columns.join(", "),
                        )
                    }
                }
            }
        })
    }
}
