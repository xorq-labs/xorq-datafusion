//! KMeans (Lloyd) fit as relational plans over an `Iterate` loop.
//!
//! Input: the KMeans input materialized once, with columns `__ml_row_id`
//! and `__ml_x{j}` (one Float64 per feature).
//!
//! Loop value (one row per cluster): `__ml_cluster` (Int64), the current
//! centers `__ml_c{j}` and the previous ones `__ml_p{j}` (null before the
//! first iteration).
//!
//! Each iteration, mirroring scikit-learn's `_kmeans_single_lloyd`:
//! 1. cross join rows with clusters; squared distances to the current and
//!    previous centers;
//! 2. per row: nearest current center and nearest previous center
//!    (`first_value(cluster ORDER BY dist, cluster)`, ties to the lowest
//!    index);
//! 3. per cluster: the mean of its rows is the new center;
//! 4. converged when no row changed cluster compared with the previous
//!    centers (scikit-learn's strict convergence: a row-local comparison, so
//!    it does not depend on summation order), or when the total squared
//!    center shift is `<= tol`.
//!
//! Clusters that receive no rows keep their previous row (upsert by
//! cluster). scikit-learn relocates them instead; inputs must not produce
//! empty clusters.

use std::sync::Arc;

use datafusion::arrow::array::{AsArray, RecordBatch};
use datafusion::arrow::datatypes::{DataType, Float64Type, Int64Type, UInt64Type};
use datafusion::catalog::MemTable;
use datafusion::common::{exec_err, plan_err, Column, DFSchema, JoinType, Result, ScalarValue};
use datafusion::datasource::provider_as_source;
use datafusion::functions_aggregate::expr_fn::{avg, first_value, max, min, sum};
use datafusion::functions_aggregate::sum::sum_udaf;
use datafusion::logical_expr::expr::WindowFunction;
use datafusion::logical_expr::{
    cast, lit, when, Expr, Extension, LogicalPlan, LogicalPlanBuilder, SortExpr,
};

use super::nodes::iterate::{ConvergenceSpec, Iterate, LoopHandle, LoopState, N_ITER};

pub(crate) const ROW_ID: &str = "__ml_row_id";
pub(crate) const CLUSTER: &str = "__ml_cluster";
pub(crate) const CONVERGED: &str = "__ml_converged";

pub(crate) fn x(j: usize) -> String {
    format!("__ml_x{j}")
}

pub(crate) fn c(j: usize) -> String {
    format!("__ml_c{j}")
}

fn p(j: usize) -> String {
    format!("__ml_p{j}")
}

fn column(name: &str) -> Expr {
    Expr::Column(Column::from_name(name))
}

fn qualified(relation: &str, name: &str) -> Expr {
    Expr::Column(Column::new(Some(relation), name))
}

fn squared_distance(n_features: usize, center: impl Fn(usize) -> String) -> Expr {
    (0..n_features)
        .map(|j| {
            let diff = column(&x(j)) - column(&center(j));
            diff.clone() * diff
        })
        .reduce(|a, b| a + b)
        .expect("at least one feature")
}

fn window_total(expr: Expr) -> Expr {
    Expr::from(WindowFunction::new(sum_udaf(), vec![expr]))
}

/// The loop value before the first iteration: the initial centers, no
/// previous centers.
fn init_plan(init: &[Vec<f64>]) -> Result<LogicalPlan> {
    let n_features = init.first().map_or(0, Vec::len);
    let rows = init
        .iter()
        .enumerate()
        .map(|(k, center)| {
            let mut row = vec![lit(k as i64)];
            row.extend(center.iter().map(|v| lit(*v)));
            row.extend((0..n_features).map(|_| lit(ScalarValue::Float64(None))));
            row
        })
        .collect();
    let mut names = vec![CLUSTER.to_string()];
    names.extend((0..n_features).map(c));
    names.extend((0..n_features).map(p));
    let values = LogicalPlanBuilder::values(rows)?.build()?;
    let renamed = values
        .schema()
        .columns()
        .into_iter()
        .zip(names)
        .map(|(col, name)| Expr::Column(col).alias(name));
    LogicalPlanBuilder::from(values).project(renamed)?.build()
}

/// One Lloyd iteration over `input` (row id + features) and the loop value
/// read through `state`.
fn body_plan(
    input: LogicalPlan,
    state: LogicalPlan,
    n_features: usize,
    tol: f64,
) -> Result<LogicalPlan> {
    let d = n_features;
    let by_distance = |distance: &str| -> Vec<SortExpr> {
        vec![
            column(distance).sort(true, false),
            column(CLUSTER).sort(true, false),
        ]
    };
    // 1. distances to current and previous centers
    let mut pairs = vec![column(ROW_ID), column(CLUSTER)];
    pairs.extend((0..d).map(|j| column(&x(j))));
    pairs.push(squared_distance(d, c).alias("__ml_dist"));
    pairs.push(squared_distance(d, p).alias("__ml_dist_prev"));
    // The loop value (k rows) is the build side; rows stream through.
    let pairs = LogicalPlanBuilder::from(state.clone())
        .cross_join(input)?
        .project(pairs)?;
    // 2. per row: nearest current and previous center
    let mut per_row = vec![
        first_value(column(CLUSTER), by_distance("__ml_dist")).alias("__ml_label"),
        first_value(column(CLUSTER), by_distance("__ml_dist_prev")).alias("__ml_label_prev"),
        max(cast(column("__ml_dist_prev").is_null(), DataType::Int64)).alias("__ml_no_prev"),
    ];
    per_row.extend((0..d).map(|j| first_value(column(&x(j)), vec![]).alias(x(j))));
    let changed = when(
        column("__ml_no_prev")
            .eq(lit(1_i64))
            .or(column("__ml_label").not_eq(column("__ml_label_prev"))),
        lit(1_i64),
    )
    .otherwise(lit(0_i64))?;
    let mut labelled = vec![column("__ml_label"), changed.alias("__ml_changed")];
    labelled.extend((0..d).map(|j| column(&x(j))));
    // 3. per cluster: new centers
    let mut per_cluster = vec![sum(column("__ml_changed")).alias("__ml_changed_k")];
    per_cluster.extend((0..d).map(|j| avg(column(&x(j))).alias(format!("__ml_m{j}"))));
    let new_centers = pairs
        .aggregate(vec![column(ROW_ID)], per_row)?
        .project(labelled)?
        .aggregate(vec![column("__ml_label")], per_cluster)?
        .alias("new")?
        .build()?;
    // 4. shift against the current centers, totals, convergence flag
    let current = LogicalPlanBuilder::from(state).alias("cur")?.build()?;
    let shift = (0..d)
        .map(|j| {
            let diff = qualified("new", &format!("__ml_m{j}")) - qualified("cur", &c(j));
            diff.clone() * diff
        })
        .reduce(|a, b| a + b)
        .expect("at least one feature");
    let mut joined = vec![
        qualified("cur", CLUSTER).alias(CLUSTER),
        qualified("new", "__ml_changed_k").alias("__ml_changed_k"),
        shift.alias("__ml_shift_k"),
    ];
    joined.extend((0..d).map(|j| qualified("new", &format!("__ml_m{j}")).alias(c(j))));
    joined.extend((0..d).map(|j| qualified("cur", &c(j)).alias(p(j))));
    let totals = [
        window_total(column("__ml_changed_k")).alias("__ml_changed_total"),
        window_total(column("__ml_shift_k")).alias("__ml_shift_total"),
    ];
    let converged = column("__ml_changed_total")
        .eq(lit(0_i64))
        .or(column("__ml_shift_total").lt_eq(lit(tol)));
    let mut output = vec![column(CLUSTER)];
    output.extend((0..d).map(|j| column(&c(j))));
    output.extend((0..d).map(|j| column(&p(j))));
    output.push(converged.alias(CONVERGED));
    LogicalPlanBuilder::from(new_centers)
        .join(
            current,
            JoinType::Inner,
            (
                vec![Column::new(Some("new"), "__ml_label")],
                vec![Column::new(Some("cur"), CLUSTER)],
            ),
            None,
        )?
        .project(joined)?
        .window(totals)?
        .project(output)?
        .build()
}

/// The `Iterate` plan fitting KMeans on `input` (row id + features) from
/// `init` centers. `tol` is absolute (scikit-learn's `_tolerance`).
pub(crate) fn kmeans_fit_plan(
    input: LogicalPlan,
    init: &[Vec<f64>],
    max_iter: usize,
    tol: f64,
) -> Result<LogicalPlan> {
    let Some(n_features) = init.first().map(Vec::len) else {
        return plan_err!("KMeans needs at least one initial center");
    };
    let init = init_plan(init)?;
    let handle = LoopHandle::default();
    let state = LogicalPlan::Extension(Extension {
        node: Arc::new(LoopState {
            handle: handle.clone(),
            schema: Arc::new(DFSchema::from_unqualified_fields(
                init.schema().fields().clone(),
                Default::default(),
            )?),
        }),
    });
    let body = body_plan(input, state, n_features, tol)?;
    let iterate = Iterate::try_new(
        init,
        body,
        vec![CLUSTER.to_string()],
        max_iter,
        ConvergenceSpec::Column(CONVERGED.to_string()),
        handle,
    )?;
    Ok(LogicalPlan::Extension(Extension {
        node: Arc::new(iterate),
    }))
}

/// Centers (cluster order) and `n_iter` from the `Iterate` output.
pub(crate) fn read_centers(
    batches: &[RecordBatch],
    n_clusters: usize,
    n_features: usize,
) -> Result<(Vec<Vec<f64>>, usize)> {
    let mut centers = vec![None; n_clusters];
    let mut n_iter = 0;
    for batch in batches {
        let cluster = batch
            .column_by_name(CLUSTER)
            .map(|a| a.as_primitive::<Int64Type>());
        let iters = batch
            .column_by_name(N_ITER)
            .map(|a| a.as_primitive::<UInt64Type>());
        let (Some(cluster), Some(iters)) = (cluster, iters) else {
            return exec_err!("KMeans fit plan output lacks {CLUSTER} or {N_ITER}");
        };
        for row in 0..batch.num_rows() {
            let k = cluster.value(row);
            let Some(slot) = usize::try_from(k).ok().and_then(|k| centers.get_mut(k)) else {
                return exec_err!("KMeans fit produced unknown cluster {k}");
            };
            let mut center = Vec::with_capacity(n_features);
            for j in 0..n_features {
                let Some(values) = batch.column_by_name(&c(j)) else {
                    return exec_err!("KMeans fit plan output lacks {}", c(j));
                };
                center.push(values.as_primitive::<Float64Type>().value(row));
            }
            *slot = Some(center);
            n_iter = iters.value(row) as usize;
        }
    }
    let centers = centers.into_iter().collect::<Option<Vec<_>>>();
    match centers {
        Some(centers) => Ok((centers, n_iter)),
        None => exec_err!("KMeans fit lost a cluster"),
    }
}

/// Sum over rows of the squared distance to the nearest of `centers`.
pub(crate) fn inertia_plan(input: LogicalPlan, centers: &[Vec<f64>]) -> Result<LogicalPlan> {
    let n_features = centers.first().map_or(0, Vec::len);
    let rows = centers
        .iter()
        .enumerate()
        .map(|(k, center)| {
            let mut row = vec![lit(k as i64)];
            row.extend(center.iter().map(|v| lit(*v)));
            row
        })
        .collect();
    let values = LogicalPlanBuilder::values(rows)?.build()?;
    let mut names = vec![CLUSTER.to_string()];
    names.extend((0..n_features).map(c));
    let renamed = values
        .schema()
        .columns()
        .into_iter()
        .zip(names)
        .map(|(col, name)| Expr::Column(col).alias(name));
    let centers = LogicalPlanBuilder::from(values).project(renamed)?.build()?;
    LogicalPlanBuilder::from(centers)
        .cross_join(input)?
        .project(vec![
            column(ROW_ID),
            squared_distance(n_features, c).alias("__ml_dist"),
        ])?
        .aggregate(
            vec![column(ROW_ID)],
            vec![min(column("__ml_dist")).alias("__ml_dist")],
        )?
        .aggregate(
            Vec::<Expr>::new(),
            vec![sum(column("__ml_dist")).alias("__ml_inertia")],
        )?
        .build()
}

/// Materialize `batches` (features `__ml_x{j}`) as a MemTable scan with a
/// `__ml_row_id` column, spread over `partitions` partitions.
pub(crate) fn materialized_input(
    batches: Vec<RecordBatch>,
    partitions: usize,
) -> Result<LogicalPlan> {
    let Some(first) = batches.first() else {
        return plan_err!("cannot fit KMeans on an input with no rows");
    };
    let mut fields = vec![Arc::new(datafusion::arrow::datatypes::Field::new(
        ROW_ID,
        DataType::UInt64,
        false,
    ))];
    fields.extend(first.schema().fields().iter().cloned());
    let schema = Arc::new(datafusion::arrow::datatypes::Schema::new(fields));
    let mut parts = vec![Vec::new(); partitions.max(1)];
    let mut offset = 0_u64;
    for (i, batch) in batches.into_iter().filter(|b| b.num_rows() > 0).enumerate() {
        let n = batch.num_rows() as u64;
        let ids = datafusion::arrow::array::UInt64Array::from_iter_values(offset..offset + n);
        offset += n;
        let mut columns: Vec<datafusion::arrow::array::ArrayRef> = vec![Arc::new(ids)];
        columns.extend(batch.columns().iter().cloned());
        let len = parts.len();
        parts[i % len].push(RecordBatch::try_new(schema.clone(), columns)?);
    }
    if offset == 0 {
        return plan_err!("cannot fit KMeans on an input with no rows");
    }
    let table = MemTable::try_new(schema, parts)?;
    LogicalPlanBuilder::scan(
        "__ml_kmeans_input",
        provider_as_source(Arc::new(table)),
        None,
    )?
    .build()
}

/// The scalar `__ml_inertia` from the inertia plan's output.
pub(crate) fn read_inertia(batches: &[RecordBatch]) -> Result<f64> {
    for batch in batches.iter().filter(|b| b.num_rows() > 0) {
        if let Some(values) = batch.column_by_name("__ml_inertia") {
            return Ok(values.as_primitive::<Float64Type>().value(0));
        }
    }
    exec_err!("KMeans inertia plan returned no rows")
}
