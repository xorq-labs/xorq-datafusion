use pyo3::{prelude::*, types::PyTuple};

use crate::pyarrow_util::arrays_to_pyarrow;
use crate::utils::{make_scalar_function, parse_volatility, with_python};
use datafusion::arrow::array::{make_array, ArrayData, ArrayRef};
use datafusion::arrow::datatypes::DataType;
use datafusion::arrow::pyarrow::{FromPyArrow, PyArrowType};
use datafusion::common::exec_err;
use datafusion::error::DataFusionError;
use datafusion_expr::create_udf;
use datafusion_expr::function::ScalarFunctionImplementation;
use datafusion_expr::ScalarUDF;

/// Create a DataFusion's UDF implementation from a python function
/// that expects pyarrow arrays. This is more efficient as it performs
/// a zero-copy of the contents.
fn to_rust_function(func: Py<PyAny>, return_type: DataType) -> ScalarFunctionImplementation {
    make_scalar_function(
        move |args: &[ArrayRef]| -> Result<ArrayRef, DataFusionError> {
            let array_data = with_python("Python UDF", |py| {
                // 1. cast args to Pyarrow arrays
                let py_args = PyTuple::new(py, arrays_to_pyarrow(args, py)?)?;

                // 2. call function
                let value = func.call(py, py_args, None)?;

                // 3. cast to arrow::array::Array
                ArrayData::from_pyarrow_bound(value.bind(py))
            })?;
            // Nothing downstream checks the type against the declared one, and
            // kernels that downcast (e.g. sum) panic on a mismatch.
            if !array_data.data_type().equals_datatype(&return_type) {
                return exec_err!(
                    "Python UDF returned an array of type {}, expected {}",
                    array_data.data_type(),
                    return_type
                );
            }
            Ok(make_array(array_data))
        },
    )
}

/// Represents a PyScalarUDF
#[pyclass(from_py_object, name = "ScalarUDF", module = "let", subclass)]
#[derive(Debug, Clone)]
pub struct PyScalarUDF {
    pub(crate) function: ScalarUDF,
}

#[pymethods]
impl PyScalarUDF {
    #[new]
    fn new(
        name: &str,
        func: Py<PyAny>,
        input_types: PyArrowType<Vec<DataType>>,
        return_type: PyArrowType<DataType>,
        volatility: &str,
    ) -> PyResult<Self> {
        let function = create_udf(
            name,
            input_types.0,
            return_type.0.clone(),
            parse_volatility(volatility)?,
            to_rust_function(func, return_type.0),
        );
        Ok(Self { function })
    }

    fn __repr__(&self) -> PyResult<String> {
        Ok(format!("ScalarUDF({})", self.function.name()))
    }
}
