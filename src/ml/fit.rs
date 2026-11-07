//! Fit: build and run the native plans that fit each pipeline step.

use datafusion::arrow::array::{Array, AsArray, RecordBatch};
use datafusion::arrow::datatypes::{DataType, Float64Type, Int64Type, UInt64Type};
use datafusion::common::{exec_err, not_impl_err, plan_err, Column, Result};
use std::sync::Arc;

use datafusion::catalog::MemTable;
use datafusion::dataframe::DataFrame;
use datafusion::datasource::provider_as_source;
use datafusion::execution::session_state::SessionState;
use datafusion::functions::core::expr_fn::get_field;
use datafusion::functions::math::expr_fn::sqrt;
use datafusion::functions_aggregate::count::count_all;
use datafusion::logical_expr::{cast, lit, when, Expr, LogicalPlan, LogicalPlanBuilder};

use super::exec::welford::{welford_udaf, COUNT, M2, MEAN};
use super::kmeans;
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

/// `input`'s features after a fitted scaler, as scikit-learn's `transform`
/// computes them (`(x - mean) / scale`, per flags), keeping the feature names.
fn transform_plan(
    input: LogicalPlan,
    features: &[String],
    scaler: &FittedStep,
) -> Result<LogicalPlan> {
    let FittedStep::StandardScaler {
        with_mean,
        with_std,
        mean,
        scale,
        ..
    } = scaler
    else {
        return plan_err!("transform_plan needs a fitted standard_scaler");
    };
    let exprs = features.iter().enumerate().map(|(j, name)| {
        let mut expr = cast(feature(name), DataType::Float64);
        if let (true, Some(mean)) = (with_mean, mean) {
            expr = expr - lit(mean[j]);
        }
        if let (true, Some(scale)) = (with_std, scale) {
            expr = expr / lit(scale[j]);
        }
        expr.alias(name)
    });
    LogicalPlanBuilder::from(input).project(exprs)?.build()
}

/// Check the KMeans input (no missing or non-finite values; the same
/// single-pass aggregate as the scaler fit, run whatever `tol` is) and
/// return scikit-learn's `_tolerance`: `tol` times its mean feature
/// variance, or 0 when `tol` is 0.
async fn validate_and_tolerance(
    state: &SessionState,
    input: &LogicalPlan,
    features: &[String],
    tol: f64,
) -> Result<f64> {
    let names: Vec<String> = (0..features.len()).map(kmeans::x).collect();
    let plan = scaler_fit_plan(input.clone(), &names)?;
    let batches = DataFrame::new(state.clone(), plan).collect().await?;
    let FittedStep::StandardScaler { var: Some(var), .. } =
        read_scaler(&batches, features, true, true)?
    else {
        return plan_err!("variance of the KMeans input is missing");
    };
    if tol == 0.0 {
        return Ok(0.0);
    }
    Ok(tol * var.iter().sum::<f64>() / features.len() as f64)
}

/// `input`'s feature columns, read from the source exactly once: a fit with
/// more than one step reads its input more than once, and a source (e.g. a
/// registered record batch reader) may be single-shot. Partitioning is kept.
async fn read_once(
    state: &SessionState,
    input: LogicalPlan,
    features: &[String],
    n_steps: usize,
) -> Result<LogicalPlan> {
    if n_steps < 2 {
        return Ok(input);
    }
    let columns = features.iter().map(|name| feature(name));
    let projected = LogicalPlanBuilder::from(input).project(columns)?.build()?;
    let partitions = DataFrame::new(state.clone(), projected.clone())
        .collect_partitioned()
        .await?;
    let schema = Arc::new(projected.schema().as_arrow().clone());
    let table = MemTable::try_new(schema, partitions)?;
    LogicalPlanBuilder::scan("__ml_fit_input", provider_as_source(Arc::new(table)), None)?.build()
}

/// Materialize the KMeans input and build its `Iterate` fit plan.
async fn prepare_kmeans(
    state: &SessionState,
    input: LogicalPlan,
    features: &[String],
    init: &[Vec<f64>],
    max_iter: usize,
    tol: f64,
) -> Result<(LogicalPlan, LogicalPlan)> {
    let renamed = features
        .iter()
        .enumerate()
        .map(|(j, name)| cast(feature(name), DataType::Float64).alias(kmeans::x(j)));
    let projected = LogicalPlanBuilder::from(input).project(renamed)?.build()?;
    let batches = DataFrame::new(state.clone(), projected).collect().await?;
    let partitions = state.config().target_partitions();
    let materialized = kmeans::materialized_input(batches, partitions)?;
    let tol = validate_and_tolerance(state, &materialized, features, tol).await?;
    let plan = kmeans::kmeans_fit_plan(materialized.clone(), init, max_iter, tol)?;
    Ok((materialized, plan))
}

/// The KMeans `Iterate` fit plan `fit` would run for `request` (executing
/// the steps before it, and the materialization of its input).
pub(crate) async fn kmeans_fit_plan_for(
    state: SessionState,
    input: LogicalPlan,
    request: &FitRequest,
) -> Result<LogicalPlan> {
    let features = &request.features;
    let mut current = read_once(&state, input, features, request.steps.len()).await?;
    for step in &request.steps {
        match step {
            StepSpec::StandardScaler {
                with_mean,
                with_std,
            } => {
                let plan = scaler_fit_plan(current.clone(), features)?;
                let batches = DataFrame::new(state.clone(), plan).collect().await?;
                let fitted = read_scaler(&batches, features, *with_mean, *with_std)?;
                current = transform_plan(current, features, &fitted)?;
            }
            StepSpec::KMeans {
                init,
                max_iter,
                tol,
                ..
            } => {
                let (_, plan) =
                    prepare_kmeans(&state, current, features, init, *max_iter, *tol).await?;
                return Ok(plan);
            }
        }
    }
    plan_err!("the fit request has no kmeans step")
}

async fn fit_kmeans(
    state: &SessionState,
    input: LogicalPlan,
    features: &[String],
    n_clusters: usize,
    init: &[Vec<f64>],
    max_iter: usize,
    tol: f64,
) -> Result<FittedStep> {
    // Materialize the (transformed) input once: the loop re-reads it every
    // iteration, and a source may be single-shot.
    let (materialized, plan) = prepare_kmeans(state, input, features, init, max_iter, tol).await?;
    let output = DataFrame::new(state.clone(), plan).collect().await?;
    let (cluster_centers, n_iter) = kmeans::read_centers(&output, n_clusters, features.len())?;
    let inertia_plan = kmeans::inertia_plan(materialized, &cluster_centers)?;
    let inertia = kmeans::read_inertia(
        &DataFrame::new(state.clone(), inertia_plan)
            .collect()
            .await?,
    )?;
    Ok(FittedStep::KMeans {
        cluster_centers,
        inertia,
        n_iter,
    })
}

/// Fit every step of `request` on `input`, planning and executing with
/// `state`. Each step sees the previous steps' output. Never calls into
/// Python.
pub(crate) async fn fit(
    state: SessionState,
    input: LogicalPlan,
    request: &FitRequest,
) -> Result<FitResult> {
    let features = &request.features;
    let mut current = read_once(&state, input, features, request.steps.len()).await?;
    let mut steps = Vec::with_capacity(request.steps.len());
    for (i, step) in request.steps.iter().enumerate() {
        match step {
            // Only KMeans consumes a transformed input so far.
            StepSpec::StandardScaler { .. } if i > 0 => {
                return not_impl_err!(
                    "steps[{i}]: a standard_scaler after another step is not supported"
                )
            }
            StepSpec::StandardScaler {
                with_mean,
                with_std,
            } => {
                let plan = scaler_fit_plan(current.clone(), features)?;
                let batches = DataFrame::new(state.clone(), plan).collect().await?;
                let fitted = read_scaler(&batches, features, *with_mean, *with_std)?;
                current = transform_plan(current, features, &fitted)?;
                steps.push(fitted);
            }
            StepSpec::KMeans {
                n_clusters,
                init,
                max_iter,
                tol,
            } => {
                let fitted = fit_kmeans(
                    &state,
                    current.clone(),
                    features,
                    *n_clusters,
                    init,
                    *max_iter,
                    *tol,
                )
                .await?;
                steps.push(fitted);
            }
        }
    }
    let result = FitResult { steps };
    result.validate(features.len())?;
    Ok(result)
}
