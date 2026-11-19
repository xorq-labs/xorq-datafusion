// Licensed to the Apache Software Foundation (ASF) under one
// or more contributor license agreements.  See the NOTICE file
// distributed with this work for additional information
// regarding copyright ownership.  The ASF licenses this file
// to you under the Apache License, Version 2.0 (the
// "License"); you may not use this file except in compliance
// with the License.  You may obtain a copy of the License at
//
//   http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing,
// software distributed under the License is distributed on an
// "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
// KIND, either express or implied.  See the License for the
// specific language governing permissions and limitations
// under the License.

use std::ops::Range;
use std::sync::Arc;

use arrow::array::{make_array, ArrayData, ArrayRef};
use datafusion::logical_expr::window_state::WindowAggState;
use datafusion::scalar::ScalarValue;
use pyo3::exceptions::{PyException, PyTypeError, PyValueError};
use pyo3::prelude::*;

use crate::common::data_type::PyScalarValue;
use crate::expr::PyExpr;
use crate::pyarrow_util::arrays_to_pyarrow;
use crate::utils::{parse_volatility, with_python};
use datafusion::arrow::datatypes::DataType;
use datafusion::arrow::pyarrow::{FromPyArrow, PyArrowType};
use datafusion::error::Result;
use datafusion::logical_expr::ptr_eq::PtrEq;
use datafusion::logical_expr::{
    PartitionEvaluator, PartitionEvaluatorFactory, Signature, Volatility, WindowUDF, WindowUDFImpl,
};
use datafusion_expr::function::{PartitionEvaluatorArgs, WindowUDFFieldArgs};
use pyo3::types::{PyList, PyTuple, PyType};

#[derive(Debug)]
struct RustPartitionEvaluator {
    evaluator: Py<PyAny>,
    // The PartitionEvaluator flag methods return a plain bool, so an exception
    // raised there could only be dropped. They are read once here instead,
    // where an exception fails the query.
    is_causal: bool,
    supports_bounded_execution: bool,
    uses_window_frame: bool,
    include_rank: bool,
}

impl RustPartitionEvaluator {
    fn new(py: Python<'_>, evaluator: Py<PyAny>) -> PyResult<Self> {
        let bound = evaluator.bind(py);
        Ok(Self {
            is_causal: read_flag(bound, "is_causal")?,
            supports_bounded_execution: read_flag(bound, "supports_bounded_execution")?,
            uses_window_frame: read_flag(bound, "uses_window_frame")?,
            include_rank: read_flag(bound, "include_rank")?,
            evaluator,
        })
    }
}

/// Call the evaluator's `name()` flag method. A missing method means `false`
/// (the `WindowEvaluator` default); an exception or a non-bool result is an
/// error.
fn read_flag(evaluator: &Bound<'_, PyAny>, name: &str) -> PyResult<bool> {
    if !evaluator.hasattr(name)? {
        return Ok(false);
    }
    evaluator.call_method0(name)?.extract()
}

impl PartitionEvaluator for RustPartitionEvaluator {
    fn memoize(&mut self, _state: &mut WindowAggState) -> Result<()> {
        with_python("UDWF memoize", |py| {
            self.evaluator.bind(py).call_method0("memoize").map(|_| ())
        })
    }

    fn get_range(&self, idx: usize, n_rows: usize) -> Result<Range<usize>> {
        with_python("UDWF get_range", |py| {
            let py_args = vec![idx.into_pyobject(py)?, n_rows.into_pyobject(py)?];
            let py_args = PyTuple::new(py, py_args)?;

            self.evaluator
                .bind(py)
                .call_method1("get_range", py_args)
                .and_then(|v| {
                    let tuple: Bound<'_, PyTuple> = v.extract()?;
                    if tuple.len() != 2 {
                        return Err(PyValueError::new_err(format!(
                            "Expected get_range to return tuple of length 2. Received length {}",
                            tuple.len()
                        )));
                    }

                    let start: usize = tuple.get_item(0)?.extract()?;
                    let end: usize = tuple.get_item(1)?.extract()?;

                    Ok(Range { start, end })
                })
        })
    }

    fn is_causal(&self) -> bool {
        self.is_causal
    }

    fn evaluate_all(&mut self, values: &[ArrayRef], num_rows: usize) -> Result<ArrayRef> {
        with_python("UDWF evaluate_all", |py| {
            let py_values = PyList::new(py, arrays_to_pyarrow(values, py)?)?;
            let py_num_rows = num_rows.into_pyobject(py)?;
            let py_args = PyTuple::new(py, vec![py_values.as_any(), &py_num_rows])?;

            self.evaluator
                .bind(py)
                .call_method1("evaluate_all", py_args)
                .and_then(|v| Ok(make_array(ArrayData::from_pyarrow_bound(&v)?)))
        })
    }

    fn evaluate(&mut self, values: &[ArrayRef], range: &Range<usize>) -> Result<ScalarValue> {
        with_python("UDWF evaluate", |py| {
            let py_values = PyList::new(py, arrays_to_pyarrow(values, py)?)?;
            let range_tuple = PyTuple::new(py, vec![range.start, range.end])?;
            let py_args = PyTuple::new(py, vec![py_values.as_any(), range_tuple.as_any()])?;

            self.evaluator
                .bind(py)
                .call_method1("evaluate", py_args)
                .and_then(|v| v.extract::<PyScalarValue>())
                .map(|v| v.0)
        })
    }

    fn evaluate_all_with_rank(
        &self,
        num_rows: usize,
        ranks_in_partition: &[Range<usize>],
    ) -> Result<ArrayRef> {
        with_python("UDWF evaluate_all_with_rank", |py| {
            let ranks = ranks_in_partition
                .iter()
                .map(|r| PyTuple::new(py, vec![r.start, r.end]))
                .collect::<PyResult<Vec<_>>>()?;

            // 1. cast args to Pyarrow array
            let py_args = vec![
                num_rows.into_pyobject(py)?.into_any(),
                PyList::new(py, ranks)?.into_any(),
            ];

            let py_args = PyTuple::new(py, py_args)?;

            // 2. call function
            self.evaluator
                .bind(py)
                .call_method1("evaluate_all_with_rank", py_args)
                .and_then(|v| Ok(make_array(ArrayData::from_pyarrow_bound(&v)?)))
        })
    }

    fn supports_bounded_execution(&self) -> bool {
        self.supports_bounded_execution
    }

    fn uses_window_frame(&self) -> bool {
        self.uses_window_frame
    }

    fn include_rank(&self) -> bool {
        self.include_rank
    }
}

/// Where each partition's Python evaluator comes from.
///
/// DataFusion asks for a new `PartitionEvaluator` per window partition, and
/// evaluators keep state (`memoize`, running totals), so each partition needs
/// its own Python object: sharing one mixes rows from different partitions.
#[derive(Debug)]
enum EvaluatorSource {
    /// Called once per partition: a `WindowEvaluator` subclass, or any callable
    /// that returns a new evaluator.
    Factory(Py<PyAny>),
    /// A single evaluator object; each partition gets a deep copy of it.
    Instance(Py<PyAny>),
}

impl EvaluatorSource {
    fn classify(evaluator: &Bound<'_, PyAny>) -> PyResult<Self> {
        // A class is callable, and so is an evaluator instance that defines
        // __call__; only something callable that is not itself an evaluator
        // (it has no evaluate_all) is a factory.
        let is_factory = evaluator.is_instance_of::<PyType>()
            || (evaluator.is_callable() && !evaluator.hasattr("evaluate_all")?);
        let evaluator = evaluator.clone().unbind();
        Ok(if is_factory {
            Self::Factory(evaluator)
        } else {
            Self::Instance(evaluator)
        })
    }

    fn create(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        match self {
            Self::Factory(factory) => {
                let evaluator = factory.bind(py).call0()?;
                // A factory returning a class or a non-evaluator would only
                // fail later with a confusing error from a method call.
                if evaluator.is_instance_of::<PyType>() || !evaluator.hasattr("evaluate_all")? {
                    return Err(PyTypeError::new_err(format!(
                        "the window evaluator factory returned {}, not a window evaluator",
                        evaluator.repr()?
                    )));
                }
                Ok(evaluator.unbind())
            }
            Self::Instance(evaluator) => py
                .import("copy")?
                .call_method1("deepcopy", (evaluator.bind(py),))
                .map(Bound::unbind)
                .map_err(|err| {
                    // Only a copy that failed is the evaluator's fault: leave
                    // KeyboardInterrupt, SystemExit and the like as they are.
                    if !err.is_instance_of::<PyException>(py) {
                        return err;
                    }
                    let wrapped = PyTypeError::new_err(format!(
                        "could not copy the window evaluator for a new partition ({err}); \
                         pass a factory instead, such as the evaluator class or a \
                         function returning a new evaluator"
                    ));
                    wrapped.set_cause(py, Some(err));
                    wrapped
                }),
        }
    }
}

fn to_rust_partition_evaluator(source: EvaluatorSource) -> PartitionEvaluatorFactory {
    Arc::new(move || -> Result<Box<dyn PartitionEvaluator>> {
        let evaluator = with_python("UDWF evaluator factory", |py| {
            let evaluator = source.create(py)?;
            RustPartitionEvaluator::new(py, evaluator)
        })?;
        Ok(Box::new(evaluator))
    })
}

/// Represents an WindowUDF
#[pyclass(from_py_object, name = "WindowUDF", module = "let", subclass)]
#[derive(Debug, Clone)]
pub struct PyWindowUDF {
    pub(crate) function: WindowUDF,
}

#[pymethods]
impl PyWindowUDF {
    #[new]
    #[pyo3(signature=(name, evaluator, input_types, return_type, volatility))]
    fn new(
        name: &str,
        evaluator: &Bound<'_, PyAny>,
        input_types: Vec<PyArrowType<DataType>>,
        return_type: PyArrowType<DataType>,
        volatility: &str,
    ) -> PyResult<Self> {
        let return_type = return_type.0;
        let input_types = input_types.into_iter().map(|t| t.0).collect();

        let function = WindowUDF::from(MultiColumnWindowUDF::new(
            name,
            input_types,
            return_type,
            parse_volatility(volatility)?,
            to_rust_partition_evaluator(EvaluatorSource::classify(evaluator)?),
        ));
        Ok(Self { function })
    }

    /// creates a new PyExpr with the call of the udf
    #[pyo3(signature = (*args))]
    fn __call__(&self, args: Vec<PyExpr>) -> PyResult<PyExpr> {
        let args = args.iter().map(|e| e.expr.clone()).collect();
        Ok(self.function.call(args).into())
    }

    fn __repr__(&self) -> PyResult<String> {
        Ok(format!("WindowUDF({})", self.function.name()))
    }
}

#[derive(Hash, Eq, PartialEq)]
pub struct MultiColumnWindowUDF {
    name: String,
    signature: Signature,
    return_type: DataType,
    partition_evaluator_factory: PtrEq<PartitionEvaluatorFactory>,
}

impl std::fmt::Debug for MultiColumnWindowUDF {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        f.debug_struct("WindowUDF")
            .field("name", &self.name)
            .field("signature", &self.signature)
            .field("return_type", &"<func>")
            .field("partition_evaluator_factory", &"<FUNC>")
            .finish()
    }
}

impl MultiColumnWindowUDF {
    pub fn new(
        name: impl Into<String>,
        input_types: Vec<DataType>,
        return_type: DataType,
        volatility: Volatility,
        partition_evaluator_factory: PartitionEvaluatorFactory,
    ) -> Self {
        let name = name.into();
        let signature = Signature::exact(input_types, volatility);
        Self {
            name,
            signature,
            return_type,
            partition_evaluator_factory: partition_evaluator_factory.into(),
        }
    }
}

impl WindowUDFImpl for MultiColumnWindowUDF {
    fn name(&self) -> &str {
        &self.name
    }

    fn signature(&self) -> &Signature {
        &self.signature
    }

    fn partition_evaluator(
        &self,
        _partition_evaluator_args: PartitionEvaluatorArgs,
    ) -> Result<Box<dyn PartitionEvaluator>> {
        let _ = _partition_evaluator_args;
        (self.partition_evaluator_factory)()
    }

    fn field(&self, field_args: WindowUDFFieldArgs) -> Result<arrow::datatypes::FieldRef> {
        // TODO: Should nullable always be `true`?
        Ok(arrow::datatypes::Field::new(field_args.name(), self.return_type.clone(), true).into())
    }
}
