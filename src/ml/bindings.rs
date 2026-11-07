//! Python bindings for the ML layer, registered as `_internal.ml`.

use pyo3::prelude::*;

pub(crate) fn init_module(_m: &Bound<'_, PyModule>) -> PyResult<()> {
    Ok(())
}
