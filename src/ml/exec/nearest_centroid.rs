//! `__ml_nearest_centroid(x_1, ..., x_d, centers, weights) -> Int64`: the
//! index of the nearest of `k` centers under
//! `sum_j weights_j * (x_j - c_kj)^2`, ties to the lowest index. `centers` is a constant list of `k * d` Float64 (row
//! major), `weights` a constant list of `d`. A row with a null or non-finite
//! feature gets a null label.

use std::sync::Arc;

use datafusion::arrow::array::{Array, AsArray, Float64Array, Int64Array};
use datafusion::arrow::datatypes::{DataType, Float64Type};
use datafusion::common::{exec_err, plan_err, Result, ScalarValue};
use datafusion::logical_expr::{
    ColumnarValue, ScalarFunctionArgs, ScalarUDF, ScalarUDFImpl, Signature, Volatility,
};

pub(crate) const NAME: &str = "__ml_nearest_centroid";

pub(crate) fn nearest_centroid_udf() -> Arc<ScalarUDF> {
    Arc::new(ScalarUDF::from(NearestCentroid {
        signature: Signature::variadic_any(Volatility::Immutable),
    }))
}

/// The constant `centers` and `weights` arguments for `centers`/`weights`.
pub(crate) fn constant_args(centers: &[Vec<f64>], weights: &[f64]) -> (ScalarValue, ScalarValue) {
    let list = |values: Vec<f64>| {
        let values: Vec<ScalarValue> = values
            .into_iter()
            .map(|v| ScalarValue::Float64(Some(v)))
            .collect();
        ScalarValue::List(ScalarValue::new_list_nullable(&values, &DataType::Float64))
    };
    (list(centers.concat()), list(weights.to_vec()))
}

#[derive(Debug, PartialEq, Eq, Hash)]
struct NearestCentroid {
    signature: Signature,
}

fn constant_list(arg: &ColumnarValue, what: &str) -> Result<Vec<f64>> {
    let ColumnarValue::Scalar(ScalarValue::List(list)) = arg else {
        return exec_err!("{NAME}: {what} must be a constant list");
    };
    if list.len() != 1 || list.is_null(0) {
        return exec_err!("{NAME}: {what} must be one non-null list");
    }
    let values = list.value(0);
    let Some(values) = values.as_primitive_opt::<Float64Type>() else {
        return exec_err!("{NAME}: {what} must be a list of Float64");
    };
    Ok(values.values().to_vec())
}

impl ScalarUDFImpl for NearestCentroid {
    fn name(&self) -> &str {
        NAME
    }

    fn signature(&self) -> &Signature {
        &self.signature
    }

    fn return_type(&self, arg_types: &[DataType]) -> Result<DataType> {
        let Some((features, _)) = arg_types.split_last_chunk::<2>() else {
            return plan_err!("{NAME} takes features, centers and weights");
        };
        if features.is_empty() || features.iter().any(|t| t != &DataType::Float64) {
            return plan_err!("{NAME} features must be one or more Float64 arguments");
        }
        Ok(DataType::Int64)
    }

    fn invoke_with_args(&self, args: ScalarFunctionArgs) -> Result<ColumnarValue> {
        let n = args.number_rows;
        let Some((features, [centers, weights])) = args.args.split_last_chunk::<2>() else {
            return exec_err!("{NAME} takes features, centers and weights");
        };
        let d = features.len();
        let centers = constant_list(centers, "centers")?;
        let weights = constant_list(weights, "weights")?;
        if d == 0 || weights.len() != d || centers.is_empty() || centers.len() % d != 0 {
            return exec_err!(
                "{NAME}: {d} features, {} weights, {} center values do not fit",
                weights.len(),
                centers.len()
            );
        }
        let columns = features
            .iter()
            .map(|f| f.to_array(n))
            .collect::<Result<Vec<_>>>()?;
        let columns: Vec<&Float64Array> = columns
            .iter()
            .map(|c| c.as_primitive::<Float64Type>())
            .collect();
        let labels: Int64Array = (0..n)
            .map(|row| {
                if columns
                    .iter()
                    .any(|c| c.is_null(row) || !c.value(row).is_finite())
                {
                    return None;
                }
                let mut best = (0_i64, f64::INFINITY);
                for (k, center) in centers.chunks_exact(d).enumerate() {
                    let dist: f64 = (0..d)
                        .map(|j| {
                            let diff = columns[j].value(row) - center[j];
                            weights[j] * diff * diff
                        })
                        .sum();
                    if dist < best.1 {
                        best = (k as i64, dist);
                    }
                }
                Some(best.0)
            })
            .collect();
        Ok(ColumnarValue::Array(Arc::new(labels)))
    }
}
