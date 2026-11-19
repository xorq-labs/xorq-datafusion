use std::sync::Arc;

use pyo3::{prelude::*, types::PyTuple};

use crate::common::data_type::PyScalarValue;
use crate::expr::PyExpr;
use crate::pyarrow_util::arrays_to_pyarrow;
use crate::utils::{parse_volatility, with_python};
use datafusion::arrow::array::{Array, ArrayRef};
use datafusion::arrow::datatypes::DataType;
use datafusion::arrow::pyarrow::{PyArrowType, ToPyArrow};
use datafusion::common::ScalarValue;
use datafusion::error::Result;
use datafusion_expr::{create_udaf, Accumulator, AccumulatorFactoryFunction, AggregateUDF};

#[derive(Debug)]
struct RustAccumulator {
    accum: Py<PyAny>,
    /// Read once when the accumulator is created: DataFusion's
    /// `supports_retract_batch` returns a plain bool, so an exception, a
    /// non-bool, or a closed gate could not be reported there.
    supports_retract_batch: bool,
}

impl RustAccumulator {
    /// A missing `supports_retract_batch` method means false.
    fn new(accum: &Bound<'_, PyAny>) -> PyResult<Self> {
        let supports_retract_batch = if accum.hasattr("supports_retract_batch")? {
            accum.call_method0("supports_retract_batch")?.extract()?
        } else {
            false
        };
        Ok(Self {
            accum: accum.clone().unbind(),
            supports_retract_batch,
        })
    }
}

impl Accumulator for RustAccumulator {
    fn update_batch(&mut self, values: &[ArrayRef]) -> Result<()> {
        with_python("UDAF update", |py| {
            let py_args = PyTuple::new(py, arrays_to_pyarrow(values, py)?)?;
            self.accum
                .bind(py)
                .call_method1("update", py_args)
                .map(|_| ())
        })
    }

    fn evaluate(&mut self) -> Result<ScalarValue> {
        with_python("UDAF evaluate", |py| {
            let result = self.accum.bind(py).call_method0("evaluate")?;
            result.extract::<PyScalarValue>().map(|sv| sv.0)
        })
    }

    fn size(&self) -> usize {
        std::mem::size_of_val(self)
    }

    fn state(&mut self) -> Result<Vec<ScalarValue>> {
        with_python("UDAF state", |py| {
            let result = self.accum.bind(py).call_method0("state")?;
            result
                .extract::<Vec<PyScalarValue>>()
                .map(|v| v.into_iter().map(|sv| sv.0).collect())
        })
    }

    fn merge_batch(&mut self, states: &[ArrayRef]) -> Result<()> {
        with_python("UDAF merge", |py| {
            let state = states[0].to_data().to_pyarrow(py)?;
            self.accum
                .bind(py)
                .call_method1("merge", (state,))
                .map(|_| ())
        })
    }

    fn retract_batch(&mut self, values: &[ArrayRef]) -> Result<()> {
        with_python("UDAF retract_batch", |py| {
            let py_args = PyTuple::new(py, arrays_to_pyarrow(values, py)?)?;
            self.accum
                .bind(py)
                .call_method1("retract_batch", py_args)
                .map(|_| ())
        })
    }

    fn supports_retract_batch(&self) -> bool {
        self.supports_retract_batch
    }
}

pub fn to_rust_accumulator(accum: Py<PyAny>) -> AccumulatorFactoryFunction {
    Arc::new(move |_| -> Result<Box<dyn Accumulator>> {
        let accum = with_python("UDAF accumulator factory", |py| {
            RustAccumulator::new(accum.bind(py).call0()?.as_any())
        })?;
        Ok(Box::new(accum))
    })
}

/// Represents an AggregateUDF
#[pyclass(from_py_object, name = "AggregateUDF", module = "let", subclass)]
#[derive(Debug, Clone)]
pub struct PyAggregateUDF {
    pub(crate) function: AggregateUDF,
}

#[pymethods]
impl PyAggregateUDF {
    #[new]
    #[pyo3(signature=(name, accumulator, input_type, return_type, state_type, volatility))]
    fn new(
        name: &str,
        accumulator: Py<PyAny>,
        input_type: PyArrowType<Vec<DataType>>,
        return_type: PyArrowType<DataType>,
        state_type: PyArrowType<Vec<DataType>>,
        volatility: &str,
    ) -> PyResult<Self> {
        let function = create_udaf(
            name,
            input_type.0,
            Arc::new(return_type.0),
            parse_volatility(volatility)?,
            to_rust_accumulator(accumulator),
            Arc::new(state_type.0),
        );
        Ok(Self { function })
    }

    /// creates a new PyExpr with the call of the udf
    #[pyo3(signature = (*args))]
    fn __call__(&self, args: Vec<PyExpr>) -> PyResult<PyExpr> {
        let args = args.iter().map(|e| e.expr.clone()).collect();
        Ok(self.function.call(args).into())
    }

    fn __repr__(&self) -> PyResult<String> {
        Ok(format!("AggregateUDF({})", self.function.name()))
    }
}
