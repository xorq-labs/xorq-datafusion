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

use super::session::has_ml;
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
    m.add_wrapped(wrap_pyfunction!(validate_fit_request))?;
    m.add_wrapped(wrap_pyfunction!(validate_fit_result))?;
    m.add_wrapped(wrap_pyfunction!(validate_compile_request))?;
    m.add_wrapped(wrap_pyfunction!(_collect_interruptible))?;
    m.add_wrapped(wrap_pyfunction!(_session_context_without_ml))?;
    Ok(())
}
