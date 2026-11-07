//! Python bindings for the ML layer, registered as `_internal.ml`.

use std::sync::Arc;

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

use datafusion::execution::runtime_env::RuntimeEnvBuilder;
use datafusion::execution::session_state::SessionStateBuilder;
use datafusion::prelude::SessionConfig;

use crate::context::{PySessionConfig, PySessionContext};
use crate::dataframe::PyDataFrame;
use crate::errors::from_datafusion_error;
use crate::utils::wait_for_future_interruptible;
use datafusion::arrow::pyarrow::ToPyArrow;

use datafusion::arrow::datatypes::{DataType, Field, Schema};
use datafusion::catalog::MemTable;
use datafusion::common::tree_node::TreeNode;
use datafusion::dataframe::DataFrame;
use datafusion::datasource::provider_as_source;
use datafusion::logical_expr::{Extension, LogicalPlan, LogicalPlanBuilder};
use datafusion::optimizer::{OptimizerContext, OptimizerRule};
use datafusion::physical_plan::displayable;

use super::nodes::predict::Predict;
use super::properties::PredictStep;
use super::rules::AffineFusion;
use super::session::{has_ml, with_ml};
use super::spec::{CompileRequest, FitRequest, FitResult};

/// Raise `ValueError` unless `df`'s session plans with the ML query planner.
///
/// Sessions built by `SessionState()` / `SessionContext()` always have it; a
/// session state built elsewhere (e.g. through FFI) may not.
#[pyfunction]
fn ensure_ml_session(df: &PyDataFrame) -> PyResult<()> {
    let (state, _) = df.df.as_ref().clone().into_parts();
    if has_ml(&state) {
        Ok(())
    } else {
        Err(PyValueError::new_err(
            "this DataFrame's session has no ML planner; build it with \
             xorq_datafusion.SessionContext() or SessionState()",
        ))
    }
}

fn to_py_err(e: datafusion::error::DataFusionError) -> PyErr {
    PyValueError::new_err(e.strip_backtrace())
}

fn to_json<T: serde::Serialize>(value: &T) -> PyResult<String> {
    serde_json::to_string(value).map_err(|e| PyValueError::new_err(e.to_string()))
}

/// Parse and validate a fit request; return it re-serialized.
#[pyfunction]
fn validate_fit_request(json: &str) -> PyResult<String> {
    to_json(&FitRequest::from_json(json).map_err(to_py_err)?)
}

/// Parse and validate a fit result for `n_features` features; return it
/// re-serialized.
#[pyfunction]
fn validate_fit_result(json: &str, n_features: usize) -> PyResult<String> {
    to_json(&FitResult::from_json(json, n_features).map_err(to_py_err)?)
}

/// Parse and validate a compile request; return it re-serialized.
#[pyfunction]
fn validate_compile_request(json: &str) -> PyResult<String> {
    to_json(&CompileRequest::from_json(json).map_err(to_py_err)?)
}

/// Fit the steps of a fit request (JSON) on `df`, natively; return the fit
/// result (JSON). Ctrl-C cancels the fit.
#[pyfunction]
fn fit(py: Python, df: &PyDataFrame, request: &str) -> PyResult<String> {
    ensure_ml_session(df)?;
    let request = FitRequest::from_json(request).map_err(to_py_err)?;
    let (state, plan) = df.df.as_ref().clone().into_parts();
    let result =
        wait_for_future_interruptible(
            py,
            async move { super::fit::fit(state, plan, &request).await },
        )?
        .map_err(to_py_err)?;
    to_json(&result)
}

/// The KMeans fit plan for a fit request (JSON) on `df`, rendered at
/// `stage` (`logical` or `optimized`). Runs the steps before KMeans.
#[pyfunction]
fn explain_fit(py: Python, df: &PyDataFrame, request: &str, stage: &str) -> PyResult<String> {
    ensure_ml_session(df)?;
    let request = FitRequest::from_json(request).map_err(to_py_err)?;
    let (state, input) = df.df.as_ref().clone().into_parts();
    let plan = wait_for_future_interruptible(py, {
        let state = state.clone();
        async move { super::fit::kmeans_fit_plan_for(state, input, &request).await }
    })?
    .map_err(to_py_err)?;
    let plan = match stage {
        "logical" => plan,
        "optimized" => state.optimize(&plan).map_err(to_py_err)?,
        other => {
            return Err(PyValueError::new_err(format!(
                "stage must be 'logical' or 'optimized', got {other:?}"
            )))
        }
    };
    let rendered = plan.display_indent().to_string();
    Ok(rendered)
}

fn predict_plan(
    input: LogicalPlan,
    request: &CompileRequest,
    output: &str,
) -> PyResult<LogicalPlan> {
    let n_features = request.features.len();
    let steps = request
        .steps
        .iter()
        .map(|s| PredictStep::from_fitted(s, n_features))
        .collect();
    let node = Predict::try_new(input, request.features.clone(), steps, output.to_string())
        .map_err(to_py_err)?;
    Ok(LogicalPlan::Extension(Extension {
        node: Arc::new(node),
    }))
}

/// `df` with an Int64 `output` column: the label the compiled pipeline
/// (compile request JSON) gives each row. Lowered when the plan is optimized.
#[pyfunction]
fn predict(df: &PyDataFrame, request: &str, output: &str) -> PyResult<PyDataFrame> {
    ensure_ml_session(df)?;
    let request = CompileRequest::from_json(request).map_err(to_py_err)?;
    let (state, input) = df.df.as_ref().clone().into_parts();
    let plan = predict_plan(input, &request, output)?;
    Ok(PyDataFrame::new(DataFrame::new(state, plan)))
}

/// The predict plan of a compile request over an empty table `input` with
/// one Float64 column per feature, at `stage`: `logical`, `fused` (after
/// `AffineFusion` only), `optimized` or `physical`.
#[pyfunction]
fn explain_predict(py: Python, request: &str, output: &str, stage: &str) -> PyResult<String> {
    let request = CompileRequest::from_json(request).map_err(to_py_err)?;
    let fields: Vec<Field> = request
        .features
        .iter()
        .map(|f| Field::new(f, DataType::Float64, true))
        .collect();
    // An empty table scan rather than an EmptyRelation: the optimizer would
    // fold every plan over an EmptyRelation away.
    let schema = Arc::new(Schema::new(fields));
    let table = MemTable::try_new(schema, vec![vec![]]).map_err(to_py_err)?;
    let input = LogicalPlanBuilder::scan("input", provider_as_source(Arc::new(table)), None)
        .and_then(|b| b.build())
        .map_err(to_py_err)?;
    let plan = predict_plan(input, &request, output)?;
    let state = with_ml(SessionStateBuilder::new().with_default_features()).build();
    let rendered = match stage {
        "logical" => plan.display_indent().to_string(),
        "fused" => {
            let config = OptimizerContext::new();
            plan.transform_up(|p| AffineFusion.rewrite(p, &config))
                .map_err(to_py_err)?
                .data
                .display_indent()
                .to_string()
        }
        "optimized" => state
            .optimize(&plan)
            .map_err(to_py_err)?
            .display_indent()
            .to_string(),
        "physical" => {
            let physical = wait_for_future_interruptible(py, {
                let (state, plan) = (state.clone(), plan.clone());
                async move { state.create_physical_plan(&plan).await }
            })?
            .map_err(to_py_err)?;
            let rendered = displayable(physical.as_ref()).indent(false).to_string();
            rendered
        }
        other => {
            return Err(PyValueError::new_err(format!(
                "stage must be logical, fused, optimized or physical, got {other:?}"
            )))
        }
    };
    Ok(rendered)
}

/// Collect `df` the way ML entry points execute plans: through
/// `wait_for_future_interruptible`, so Ctrl-C cancels the query and raises
/// `KeyboardInterrupt`.
#[pyfunction]
fn _collect_interruptible<'py>(
    py: Python<'py>,
    df: &PyDataFrame,
) -> PyResult<Vec<Bound<'py, PyAny>>> {
    let batches = wait_for_future_interruptible(py, df.df.as_ref().clone().collect())?
        .map_err(from_datafusion_error)?;
    batches.into_iter().map(|rb| rb.to_pyarrow(py)).collect()
}

/// Test support: a `SessionContext` built exactly as `SessionContext(config)`
/// builds one, minus `with_ml`. Lets tests prove `with_ml` is inert.
#[pyfunction]
fn _session_context_without_ml(config: Option<PySessionConfig>) -> PyResult<PySessionContext> {
    let config = config
        .map(|c| c.config)
        .unwrap_or_else(|| SessionConfig::default().with_information_schema(true));
    let runtime = RuntimeEnvBuilder::default()
        .build()
        .map_err(from_datafusion_error)?;
    let state = SessionStateBuilder::new()
        .with_config(config)
        .with_runtime_env(Arc::new(runtime))
        .with_default_features()
        .build();
    Ok(PySessionContext::from_session_state(state))
}

pub(crate) fn init_module(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_wrapped(wrap_pyfunction!(ensure_ml_session))?;
    m.add_wrapped(wrap_pyfunction!(fit))?;
    m.add_wrapped(wrap_pyfunction!(explain_fit))?;
    m.add_wrapped(wrap_pyfunction!(predict))?;
    m.add_wrapped(wrap_pyfunction!(explain_predict))?;
    m.add_wrapped(wrap_pyfunction!(validate_fit_request))?;
    m.add_wrapped(wrap_pyfunction!(validate_fit_result))?;
    m.add_wrapped(wrap_pyfunction!(validate_compile_request))?;
    m.add_wrapped(wrap_pyfunction!(_collect_interruptible))?;
    m.add_wrapped(wrap_pyfunction!(_session_context_without_ml))?;
    Ok(())
}
