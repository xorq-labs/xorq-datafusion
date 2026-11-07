//! Fit: build and run the native plans that fit each pipeline step.

use datafusion::arrow::array::{Array, AsArray, RecordBatch};
use datafusion::arrow::datatypes::{DataType, Float64Type, Int64Type, UInt64Type};
use datafusion::common::{exec_err, not_impl_err, plan_err, Column, Result};
use datafusion::dataframe::DataFrame;
use datafusion::execution::session_state::SessionState;
use datafusion::functions::core::expr_fn::get_field;
use datafusion::functions::math::expr_fn::sqrt;
use datafusion::functions_aggregate::count::count_all;
use datafusion::logical_expr::{cast, lit, when, Expr, LogicalPlan, LogicalPlanBuilder};

use super::exec::welford::{welford_udaf, COUNT, M2, MEAN};
use super::spec::{FitRequest, FitResult, FittedStep, StepSpec};

/// `f64::EPSILON`, as scikit-learn's `_is_constant_feature` uses.
const EPS: f64 = f64::EPSILON;

fn feature(name: &str) -> Expr {
    // `from_name`, not `col`: a feature name is never parsed as `table.column`.
    Expr::Column(Column::from_name(name))
}

/// Total input rows, beside each feature's non-null count.
const ROWS: &str = "__ml_rows";

fn stat(i: usize, what: &str) -> String {
    format!("__ml_{what}_{i}")
}

/// One aggregate over `input`, one `__ml_welford` per feature plus the row
/// count (a single pass over the data), projected to the row count and
/// per-feature `count` (non-null values), `mean`, `var` (`M2 / n`, ddof=0)
/// and `scale`.
///
/// `scale` follows scikit-learn: `sqrt(var)`, or 1.0 for a feature
/// `_is_constant_feature` deems constant, i.e.
/// `var <= n * eps * var + (n * mean * eps)^2`.
pub(crate) fn scaler_fit_plan(input: LogicalPlan, features: &[String]) -> Result<LogicalPlan> {
    let welford = welford_udaf();
    let aggregates = features
        .iter()
        .enumerate()
        .map(|(i, name)| {
            welford
                .call(vec![cast(feature(name), DataType::Float64)])
                .alias(stat(i, "welford"))
        })
        .chain([count_all().alias(ROWS)]);
    let mut projection = Vec::with_capacity(4 * features.len() + 1);
    projection.push(feature(ROWS));
    for i in 0..features.len() {
        let w = || feature(&stat(i, "welford"));
        let count = get_field(w(), COUNT);
        let n = cast(count.clone(), DataType::Float64);
        let mean = get_field(w(), MEAN);
        let var = get_field(w(), M2) / n.clone();
        let bound = n.clone() * lit(EPS) * var.clone()
            + (n.clone() * mean.clone() * lit(EPS)) * (n * mean.clone() * lit(EPS));
        let scale = when(var.clone().lt_eq(bound), lit(1.0_f64)).otherwise(sqrt(var.clone()))?;
        projection.extend([
            count.alias(stat(i, "count")),
            mean.alias(stat(i, "mean")),
            var.alias(stat(i, "var")),
            scale.alias(stat(i, "scale")),
        ]);
    }
    LogicalPlanBuilder::from(input)
        .aggregate(Vec::<Expr>::new(), aggregates)?
        .project(projection)?
        .build()
}

fn column<'a>(batch: &'a RecordBatch, name: &str) -> Result<&'a dyn Array> {
    match batch.column_by_name(name) {
        Some(array) => Ok(array.as_ref()),
        None => exec_err!("ML fit plan produced no column {name}"),
    }
}

fn read_scaler(
    batches: &[RecordBatch],
    features: &[String],
    with_mean: bool,
    with_std: bool,
) -> Result<FittedStep> {
    let rows: Vec<&RecordBatch> = batches.iter().filter(|b| b.num_rows() > 0).collect();
    let [batch] = rows.as_slice() else {
        return exec_err!(
            "ML scaler fit plan must return one row, got {} batches",
            rows.len()
        );
    };
    let rows = column(batch, ROWS)?.as_primitive::<Int64Type>().value(0);
    let n_samples_seen = u64::try_from(rows).unwrap_or_default();
    if n_samples_seen == 0 {
        return plan_err!("cannot fit on an input with no rows");
    }
    let (mut means, mut vars, mut scales) = (vec![], vec![], vec![]);
    for (i, name) in features.iter().enumerate() {
        let count = column(batch, &stat(i, "count"))?
            .as_primitive::<UInt64Type>()
            .value(0);
        if count != n_samples_seen {
            return plan_err!(
                "feature {name:?} has {} missing values out of {n_samples_seen} rows; \
                 features with missing values are not supported",
                n_samples_seen - count
            );
        }
        let read = |what| -> Result<f64> {
            Ok(column(batch, &stat(i, what))?
                .as_primitive::<Float64Type>()
                .value(0))
        };
        let (mean, var) = (read("mean")?, read("var")?);
        if !(mean.is_finite() && var.is_finite()) {
            return plan_err!(
                "feature {name:?} contains NaN or infinite values, or values whose \
                 variance overflows; they are not supported"
            );
        }
        means.push(mean);
        vars.push(var);
        scales.push(read("scale")?);
    }
    Ok(FittedStep::StandardScaler {
        with_mean,
        with_std,
        mean: (with_mean || with_std).then_some(means),
        var: with_std.then_some(vars),
        scale: with_std.then_some(scales),
        n_samples_seen,
    })
}

/// Fit every step of `request` on `input`, planning and executing with
/// `state`. Never calls into Python.
pub(crate) async fn fit(
    state: SessionState,
    input: LogicalPlan,
    request: &FitRequest,
) -> Result<FitResult> {
    let mut steps = Vec::with_capacity(request.steps.len());
    for (i, step) in request.steps.iter().enumerate() {
        match step {
            // A later step must see the earlier steps' output, and only
            // KMeans consumes a transformed input so far.
            StepSpec::StandardScaler { .. } if i > 0 => {
                return not_impl_err!(
                    "steps[{i}]: a standard_scaler after another step is not supported"
                )
            }
            StepSpec::StandardScaler {
                with_mean,
                with_std,
            } => {
                let plan = scaler_fit_plan(input.clone(), &request.features)?;
                let batches = DataFrame::new(state.clone(), plan).collect().await?;
                steps.push(read_scaler(
                    &batches,
                    &request.features,
                    *with_mean,
                    *with_std,
                )?);
            }
            StepSpec::KMeans { .. } => {
                return not_impl_err!("native KMeans fit is not implemented yet")
            }
        }
    }
    let result = FitResult { steps };
    result.validate(request.features.len())?;
    Ok(result)
}
