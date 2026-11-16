use crate::sql::{builder, parser};
use pyo3::prelude::*;
#[allow(clippy::borrow_deref_ref)]
pub mod catalog;
pub mod common;
#[allow(clippy::borrow_deref_ref)]
mod context;
mod dataframe;
mod dataset;
mod dataset_exec;
mod errors;
pub mod expr;
mod ffi_table_provider;
mod functions;
mod ibis_filter_expression;
mod ibis_table;
mod ibis_table_exec;
pub mod model;
mod optimizer;
pub mod physical_plan;
mod provider;
mod py_record_batch_provider;
mod pyarrow_filter_expression;
pub mod pyarrow_util;
mod record_batch;
pub mod sql;
#[allow(clippy::borrow_deref_ref)]
mod udaf;
#[allow(clippy::borrow_deref_ref)]
mod udf;
mod udwf;
pub mod utils;

mod object_storage;

/// Handle to the process-wide tokio runtime, exposed so Python can shut it
/// down before sys.exit() to avoid a Py_Finalize / blocking-pool deadlock.
#[pyclass(name = "TokioRuntime", module = "xorq_datafusion._internal")]
struct TokioRuntime;

#[pymethods]
impl TokioRuntime {
    /// Stop pull threads from entering Python, wait up to `pull_timeout_secs`
    /// for the ones already inside to return, then shut the runtime down
    /// (waiting up to `timeout_secs`). For both, `None` means do not wait;
    /// `pull_timeout_secs` also takes `inf` for no limit. The default lives in
    /// the Python `close()`.
    ///
    /// Returns `False` when some pull was still inside Python at the deadline.
    /// Every later scan of a Python-backed table fails: this is meant for
    /// interpreter exit.
    #[pyo3(signature = (timeout_secs=None, pull_timeout_secs=None))]
    fn shutdown(
        &self,
        py: Python,
        timeout_secs: Option<u64>,
        pull_timeout_secs: Option<f64>,
    ) -> bool {
        // NaN and negatives mean no wait; too large for a Duration (inf) means no
        // limit.
        let pull_timeout = match pull_timeout_secs {
            None => Some(std::time::Duration::ZERO),
            Some(secs) => std::time::Duration::try_from_secs_f64(secs.max(0.0)).ok(),
        };
        // GIL released for both waits: an in-flight pull needs it to finish.
        py.detach(|| {
            let quiesced = crate::utils::quiesce_python_pulls(pull_timeout);
            crate::utils::shutdown_runtime(timeout_secs);
            quiesced
        })
    }
}

/// Low-level xorq internal package.
#[pymodule]
fn _internal(py: Python, m: Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<TokioRuntime>()?;
    m.add("runtime", pyo3::Py::new(py, TokioRuntime {})?)?;

    m.add_class::<context::PySessionConfig>()?;
    m.add_class::<context::PySessionContext>()?;
    m.add_class::<context::PySessionState>()?;
    m.add_class::<dataframe::PyDataFrame>()?;
    m.add_class::<udf::PyScalarUDF>()?;
    m.add_class::<udaf::PyAggregateUDF>()?;
    m.add_class::<udwf::PyWindowUDF>()?;
    m.add_class::<sql::logical::PyLogicalPlan>()?;
    m.add_class::<physical_plan::PyExecutionPlan>()?;
    m.add_class::<parser::PyContextProvider>()?;
    m.add_class::<builder::PyLogicalPlanBuilder>()?;
    m.add_class::<optimizer::PyOptimizerContext>()?;
    m.add_class::<optimizer::PyOptimizerRule>()?;
    m.add_class::<provider::PyTableProvider>()?;
    m.add_class::<catalog::PyTable>()?;

    // Register `common` as a submodule. Matching `datafusion-common` https://docs.rs/datafusion-common/latest/datafusion_common/
    let common = PyModule::new(py, "common")?;
    common::init_module(&common)?;
    m.add_submodule(&common)?;

    // Register `expr` as a submodule. Matching `datafusion-expr` https://docs.rs/datafusion-expr/latest/datafusion_expr/
    let expr = PyModule::new(py, "expr")?;
    expr::init_module(&expr)?;
    m.add_submodule(&expr)?;

    let parser = PyModule::new(py, "parser")?;
    parser::init_module(&parser)?;
    m.add_submodule(&parser)?;

    let optimizer = PyModule::new(py, "optimizer")?;
    optimizer::init_module(&optimizer)?;
    m.add_submodule(&optimizer)?;

    let builder = PyModule::new(py, "builder")?;
    builder::init_module(&builder)?;
    m.add_submodule(&builder)?;

    Ok(())
}
