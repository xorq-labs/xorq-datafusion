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

use std::any::Any;
use std::sync::Arc;

use async_trait::async_trait;
use datafusion::arrow::datatypes::SchemaRef;
use datafusion::arrow::pyarrow::PyArrowType;
use datafusion::catalog::Session;
use datafusion::datasource::{TableProvider, TableType};
use datafusion::error::{DataFusionError, Result as DFResult};
use datafusion::logical_expr::TableProviderFilterPushDown;
use datafusion::physical_plan::ExecutionPlan;
use datafusion_expr::Expr;
use pyo3::exceptions::PyValueError;
/// Implements a Datafusion TableProvider that delegates to a PyArrow Dataset
/// This allows us to use PyArrow Datasets as Datafusion tables while pushing down projections and filters
use pyo3::prelude::*;
use pyo3::types::PyType;

use crate::dataset_exec::DatasetExec;
use crate::pyarrow_filter_expression::PyArrowFilterExpression;

// Wraps a pyarrow.dataset.Dataset class and implements a Datafusion TableProvider around it
#[derive(Debug)]
pub(crate) struct Dataset {
    dataset: Py<PyAny>,
    /// Read once here rather than on every `schema()` call. `schema()` is called
    /// while planning, so reading it there took the GIL on whichever thread is
    /// planning -- frequently an async worker, where holding the GIL risks the
    /// GIL/mutex inversion. Reading it here also lets a bad schema fail
    /// registration instead of panicking mid-plan.
    schema: SchemaRef,
}

impl Dataset {
    // Creates a Python PyArrow.Dataset
    pub fn new(dataset: &Bound<'_, PyAny>, py: Python) -> PyResult<Self> {
        // Ensure that we were passed an instance of pyarrow.dataset.Dataset
        let ds = PyModule::import(py, "pyarrow.dataset")?;
        let ds_attr = ds.getattr("Dataset")?;
        let ds_type = ds_attr.cast::<PyType>()?;
        if dataset.is_instance(ds_type)? {
            let schema = Arc::new(dataset.getattr("schema")?.extract::<PyArrowType<_>>()?.0);
            Ok(Dataset {
                dataset: dataset.clone().unbind(),
                schema,
            })
        } else {
            Err(PyValueError::new_err(
                "dataset argument must be a pyarrow.dataset.Dataset object",
            ))
        }
    }
}

#[async_trait]
impl TableProvider for Dataset {
    fn as_any(&self) -> &dyn Any {
        self
    }

    fn schema(&self) -> SchemaRef {
        self.schema.clone()
    }

    fn table_type(&self) -> TableType {
        TableType::Base
    }

    async fn scan(
        &self,
        _ctx: &dyn Session,
        projection: Option<&Vec<usize>>,
        filters: &[Expr],
        _limit: Option<usize>,
    ) -> DFResult<Arc<dyn ExecutionPlan>> {
        Python::attach(|py| {
            let plan: Arc<dyn ExecutionPlan> = Arc::new(
                DatasetExec::new(py, self.dataset.bind(py), projection.cloned(), filters)
                    .map_err(|err| DataFusionError::External(Box::new(err)))?,
            );
            Ok(plan)
        })
    }

    fn supports_filters_pushdown(
        &self,
        filters: &[&Expr],
    ) -> DFResult<Vec<TableProviderFilterPushDown>> {
        filters
            .iter()
            .map(|&f| match PyArrowFilterExpression::try_from(f) {
                Ok(_) => Ok(TableProviderFilterPushDown::Exact),
                _ => Ok(TableProviderFilterPushDown::Unsupported),
            })
            .collect()
    }
}
