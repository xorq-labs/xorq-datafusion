//! Experimental native ML layer: fit and predict scikit-learn pipelines
//! inside DataFusion.
//!
//! The Python frontend (`xorq_datafusion.ml`) only inspects scikit-learn
//! objects and exchanges JSON specs with this module; all computation on row
//! data happens in native DataFusion plans built here. No ML plan ever calls
//! back into Python.
//!
//! Layout:
//! - `spec`: serde types for the pipeline spec exchanged with Python
//! - `properties`: `StepProperties`, what rewrite rules match on
//! - `nodes`: custom logical nodes (`UserDefinedLogicalNodeCore`)
//! - `rules`: optimizer rules over those nodes
//! - `exec`: physical operators, UDFs and UDAFs
//! - `planner`: extension planner and query planner
//! - `session`: `with_ml`, installing the planner and rules on a session
//! - `bindings`: the `#[pyfunction]`s and classes exposed as `_internal.ml`

pub(crate) mod bindings;
pub(crate) mod exec;
pub(crate) mod nodes;
pub(crate) mod planner;
pub(crate) mod properties;
pub(crate) mod rules;
pub(crate) mod session;
pub(crate) mod spec;

use pyo3::prelude::*;

/// Populate the `_internal.ml` submodule.
pub(crate) fn init_module(m: &Bound<'_, PyModule>) -> PyResult<()> {
    bindings::init_module(m)
}
