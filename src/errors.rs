use core::fmt;
use std::error::Error;
use std::fmt::{Debug, Display, Formatter};

use datafusion::arrow::error::ArrowError;
use datafusion::error::DataFusionError;
use pyo3::exceptions::PyValueError;
use pyo3::PyErr;

#[derive(Debug)]
pub struct PyDataFusionError(pub DataFusionError);

impl From<ArrowError> for PyDataFusionError {
    fn from(err: ArrowError) -> PyDataFusionError {
        PyDataFusionError(DataFusionError::from(err))
    }
}

impl From<PyDataFusionError> for DataFusionError {
    fn from(err: PyDataFusionError) -> DataFusionError {
        err.0
    }
}

impl From<PyErr> for PyDataFusionError {
    fn from(err: PyErr) -> PyDataFusionError {
        PyDataFusionError(DataFusionError::External(Box::new(err)))
    }
}

impl From<PyDataFusionError> for PyErr {
    fn from(err: PyDataFusionError) -> PyErr {
        match err.0 {
            DataFusionError::External(boxed) => match boxed.downcast::<PyErr>() {
                Ok(py_err) => *py_err,
                Err(original_boxed) => PyValueError::new_err(format!("{original_boxed}")),
            },
            _ => PyValueError::new_err(format!("{}", err.0)),
        }
    }
}

impl Display for PyDataFusionError {
    fn fmt(&self, f: &mut Formatter<'_>) -> fmt::Result {
        std::fmt::Display::fmt(&self.0, f)
    }
}

impl Error for PyDataFusionError {}

pub fn py_runtime_err(e: impl Debug) -> PyErr {
    PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("{e:?}"))
}

pub fn py_datafusion_err(e: impl Debug) -> PyErr {
    PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("{e:?}"))
}

pub fn py_unsupported_variant_err(e: impl Debug) -> PyErr {
    PyErr::new::<pyo3::exceptions::PyValueError, _>(format!("{e:?}"))
}
