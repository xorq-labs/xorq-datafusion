use std::sync::Arc;

use arrow::datatypes::SchemaRef;
use arrow::pyarrow::PyArrowType;
use async_trait::async_trait;
use datafusion::catalog::Session;
use datafusion::datasource::TableProvider;
use datafusion::physical_plan::ExecutionPlan;
use datafusion_expr::{Expr, TableProviderFilterPushDown, TableType};
use pyo3::types::{IntoPyDict, PyAnyMethods, PyTuple};
use pyo3::{pyclass, pymethods, PyAny, PyResult};

use crate::ibis_filter_expression::IbisFilterExpression;
use crate::ibis_table_exec::IbisTableExec;

use crate::utils::with_python;
use pyo3::prelude::*;

#[pyclass(name = "TableProvider", module = "let", subclass)]
#[derive(Debug)]
pub struct PyTableProvider {
    table_provider: Py<PyAny>,
    /// Read once here rather than on every `schema()` call, which called back
    /// into user Python. `schema()` is called while planning, so that callback
    /// held the GIL on whichever thread is planning -- frequently an async
    /// worker, where holding the GIL risks the GIL/mutex inversion. A provider
    /// whose `schema()` itself re-enters the runtime therefore does so here, on
    /// the registering thread, instead of from inside the outer query's
    /// `block_on`. Reading it here also lets a failing `schema()` surface as a
    /// registration error instead of panicking mid-plan.
    schema: SchemaRef,
}

#[pymethods]
impl PyTableProvider {
    #[new]
    #[pyo3(signature=(table_provider))]
    pub fn new(table_provider: &Bound<'_, PyAny>) -> PyResult<Self> {
        let schema = Arc::new(
            table_provider
                .call_method0("schema")?
                .extract::<PyArrowType<_>>()?
                .0,
        );
        Ok(Self {
            table_provider: table_provider.clone().into(),
            schema,
        })
    }
}

#[async_trait]
impl TableProvider for PyTableProvider {
    fn schema(&self) -> SchemaRef {
        self.schema.clone()
    }

    fn table_type(&self) -> TableType {
        TableType::Base
    }

    async fn scan(
        &self,
        _state: &dyn Session,
        projection: Option<&[usize]>,
        filters: &[Expr],
        _limit: Option<usize>,
    ) -> datafusion_common::Result<Arc<dyn ExecutionPlan>> {
        with_python("Python TableProvider.scan", |py| -> PyResult<_> {
            // Only filters supports_filters_pushdown accepted reach here, but the
            // conversion calls into Python again and can still fail. Via PyErr so a
            // Python exception keeps its type.
            let args = filters
                .iter()
                .map(|filter| {
                    Ok(IbisFilterExpression::try_from(filter)?
                        .inner()
                        .clone_ref(py))
                })
                .collect::<PyResult<Vec<Py<PyAny>>>>()?;
            let kwargs = [("filters", PyTuple::new(py, &args)?)].into_py_dict(py)?;

            let table = self
                .table_provider
                .bind(py)
                .call_method("scan", (), Some(&kwargs))?;

            let plan: Arc<dyn ExecutionPlan> =
                Arc::new(IbisTableExec::new(py, &table, projection)?);
            Ok(plan)
        })
    }

    fn supports_filters_pushdown(
        &self,
        filters: &[&Expr],
    ) -> datafusion_common::Result<Vec<TableProviderFilterPushDown>> {
        // The conversion calls into Python.
        with_python("Python TableProvider filter pushdown", |_py| {
            filters
                .iter()
                .map(|&filter| match IbisFilterExpression::try_from(filter) {
                    Ok(_) => Ok(TableProviderFilterPushDown::Exact),
                    _ => Ok(TableProviderFilterPushDown::Unsupported),
                })
                .collect::<datafusion_common::Result<Vec<_>>>()
        })
    }
}
