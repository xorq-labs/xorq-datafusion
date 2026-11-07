//! ML optimizer rules. They match `StepProperties`, never concrete step types.

use std::sync::Arc;

use datafusion::arrow::datatypes::DataType;
use datafusion::common::tree_node::Transformed;
use datafusion::common::{plan_err, Column, Result};
use datafusion::logical_expr::{cast, lit, Expr, Extension, LogicalPlan, LogicalPlanBuilder};
use datafusion::optimizer::{ApplyOrder, OptimizerConfig, OptimizerRule};

use super::exec::nearest_centroid::{constant_args, nearest_centroid_udf};
use super::nodes::predict::Predict;
use super::properties::{PredictStep, StepProperties};

/// Every ML optimizer rule, in the order `with_ml` appends them after
/// DataFusion's defaults. `AffineFusion` must run before `LowerPredict`.
pub(crate) fn all() -> Vec<Arc<dyn OptimizerRule + Send + Sync>> {
    vec![Arc::new(AffineFusion), Arc::new(LowerPredict)]
}

fn as_predict(plan: &LogicalPlan) -> Option<&Predict> {
    match plan {
        LogicalPlan::Extension(ext) => ext.node.as_any().downcast_ref::<Predict>(),
        _ => None,
    }
}

/// Fold a diagonal-affine step followed by a nearest-centroid step into one
/// weighted nearest-centroid step in the affine step's input space:
/// `(x - s) / a` nearest to `c` under weights `w` is `x` nearest to
/// `c' = s + a * c` under weights `w / a^2`. Exact in real arithmetic; in
/// floating point it is applied only when the rounding it introduces is
/// negligible next to the distance between centers (see `fuse`), so labels
/// can differ from the unfused plan only for rows within that rounding of a
/// decision boundary.
#[derive(Debug, Default)]
pub(crate) struct AffineFusion;

/// Fusion must not move any center by more than this fraction of the
/// distance between the two closest centers.
const FUSION_TOLERANCE: f64 = 1e-9;

/// Above this many coordinate comparisons, an inconclusive separation check
/// gives up (and fusion is skipped) rather than slow planning down.
const MAX_PAIRWISE_WORK: usize = 50_000_000;

/// A conservative bound, in the predictor's (scaled) space, on how far the
/// rounding in `c' = s + a * c` and in the fused distance can move a center:
/// a few ulps of the magnitudes involved, divided by the scale.
fn fusion_error_bound(shift: &[f64], scale: &[f64], centers: &[Vec<f64>]) -> f64 {
    centers
        .iter()
        .flat_map(|c| {
            (0..c.len()).map(|j| {
                4.0 * f64::EPSILON * (shift[j].abs() + (scale[j] * c[j]).abs()) / scale[j].abs()
            })
        })
        .fold(0.0, f64::max)
}

/// A lower bound on the smallest Chebyshev distance between two centers:
/// every pair differs by at least the smallest gap of any one coordinate,
/// so the largest such gap bounds them all. O(d * k log k).
fn separation_lower_bound(centers: &[Vec<f64>]) -> f64 {
    let d = centers.first().map_or(0, Vec::len);
    (0..d)
        .map(|j| {
            let mut values: Vec<f64> = centers.iter().map(|c| c[j]).collect();
            values.sort_by(f64::total_cmp);
            values
                .windows(2)
                .map(|w| w[1] - w[0])
                .fold(f64::INFINITY, f64::min)
        })
        .fold(0.0, f64::max)
}

/// Whether every pair of centers is at least `min` apart (Chebyshev).
/// Stops at the first pair that is not; `false` past `MAX_PAIRWISE_WORK`.
fn all_pairs_separated(centers: &[Vec<f64>], min: f64) -> bool {
    let k = centers.len();
    let d = centers.first().map_or(0, Vec::len);
    if k.saturating_mul(k).saturating_mul(d) / 2 > MAX_PAIRWISE_WORK {
        return false;
    }
    centers.iter().enumerate().all(|(i, a)| {
        centers[i + 1..]
            .iter()
            .all(|b| a.iter().zip(b).any(|(x, y)| (x - y).abs() >= min))
    })
}

/// Whether fusing cannot move a center by more than `FUSION_TOLERANCE` of
/// the closest center spacing.
fn fusion_is_negligible(shift: &[f64], scale: &[f64], centers: &[Vec<f64>]) -> bool {
    if centers.len() < 2 {
        return true;
    }
    let need = fusion_error_bound(shift, scale, centers) / FUSION_TOLERANCE;
    if !need.is_finite() {
        return false;
    }
    separation_lower_bound(centers) >= need || all_pairs_separated(centers, need)
}

fn fuse(affine: &PredictStep, predictor: &PredictStep) -> Option<PredictStep> {
    // Folding is only sound for per-row steps, and the folded step must be
    // linear for the change of variables to hold.
    if !(affine.is_linear() && affine.is_row_wise() && predictor.is_row_wise()) {
        return None;
    }
    let (shift, scale) = affine.diagonal_affine()?;
    let (centers, weights) = predictor.nearest_centroid()?;
    let fused_centers: Vec<Vec<f64>> = centers
        .iter()
        .map(|c| (0..c.len()).map(|j| shift[j] + scale[j] * c[j]).collect())
        .collect();
    let fused_weights: Vec<f64> = (0..weights.len())
        .map(|j| weights[j] / (scale[j] * scale[j]))
        .collect();
    // Fusion changes the arithmetic. Keep the original steps unless that
    // change is negligible: every weight and center finite (tiny or huge
    // scales overflow), and the rounding small next to the center spacing
    // (huge shifts or centers lose the low bits of `s + a * c`).
    let finite = fused_weights.iter().all(|w| w.is_finite() && *w > 0.0)
        && fused_centers.iter().flatten().all(|c| c.is_finite());
    // A predictor that already guards its input carries an earlier fold;
    // guards do not compose, so fold at most once.
    if !(predictor.input_guards().is_empty()
        && in_safe_domain(shift, scale, centers)
        && finite
        && fusion_is_negligible(shift, scale, centers))
    {
        return None;
    }
    Some(PredictStep::NearestCentroid {
        centers: fused_centers,
        weights: fused_weights,
        // Where the unfolded `(x - s) / a` is not finite the unfolded plan
        // labels null; the guard repeats exactly that arithmetic per row.
        guards: shift.iter().copied().zip(scale.iter().copied()).collect(),
    })
}

/// The magnitudes fusion accepts (decided in kata gykw, option b): every
/// shift, scale and center is zero (not for scales) or a normal float in
/// `[2^-500, 2^500]`. Outside it the error bound itself can underflow or
/// overflow, so it cannot vouch for the fusion.
fn in_safe_domain(shift: &[f64], scale: &[f64], centers: &[Vec<f64>]) -> bool {
    let (min, max) = (2f64.powi(-500), 2f64.powi(500));
    let normal = |v: f64| v.is_normal() && (min..=max).contains(&v.abs());
    shift.iter().all(|&s| s == 0.0 || normal(s))
        && scale.iter().all(|&a| normal(a))
        && centers.iter().flatten().all(|&c| c == 0.0 || normal(c))
}

impl OptimizerRule for AffineFusion {
    fn name(&self) -> &str {
        "ml_affine_fusion"
    }

    fn apply_order(&self) -> Option<ApplyOrder> {
        Some(ApplyOrder::BottomUp)
    }

    fn supports_rewrite(&self) -> bool {
        true
    }

    fn rewrite(
        &self,
        plan: LogicalPlan,
        _config: &dyn OptimizerConfig,
    ) -> Result<Transformed<LogicalPlan>> {
        let Some(predict) = as_predict(&plan) else {
            return Ok(Transformed::no(plan));
        };
        let mut steps = predict.steps.clone();
        let mut fused = false;
        let mut i = 0;
        while i + 1 < steps.len() {
            if let Some(step) = fuse(&steps[i], &steps[i + 1]) {
                steps.splice(i..i + 2, [step]);
                fused = true;
            } else {
                i += 1;
            }
        }
        if !fused {
            return Ok(Transformed::no(plan));
        }
        let predict = Predict::try_new(
            predict.input.clone(),
            predict.features.clone(),
            steps,
            predict.output.clone(),
        )?;
        Ok(Transformed::yes(LogicalPlan::Extension(Extension {
            node: Arc::new(predict),
        })))
    }
}

/// Rewrite `Predict` into a `Projection`: the input's columns plus the label,
/// computed by applying each diagonal-affine step to the features as
/// expressions and the final nearest-centroid step with
/// `__ml_nearest_centroid`.
#[derive(Debug, Default)]
pub(crate) struct LowerPredict;

impl OptimizerRule for LowerPredict {
    fn name(&self) -> &str {
        "ml_lower_predict"
    }

    fn apply_order(&self) -> Option<ApplyOrder> {
        Some(ApplyOrder::BottomUp)
    }

    fn supports_rewrite(&self) -> bool {
        true
    }

    fn rewrite(
        &self,
        plan: LogicalPlan,
        _config: &dyn OptimizerConfig,
    ) -> Result<Transformed<LogicalPlan>> {
        let Some(predict) = as_predict(&plan) else {
            return Ok(Transformed::no(plan));
        };
        let mut features: Vec<Expr> = predict
            .features
            .iter()
            .map(|name| cast(Expr::Column(Column::from_name(name)), DataType::Float64))
            .collect();
        let mut label = None;
        for step in &predict.steps {
            if let Some((shift, scale)) = step.diagonal_affine() {
                features = features
                    .into_iter()
                    .enumerate()
                    .map(|(j, x)| (x - lit(shift[j])) / lit(scale[j]))
                    .collect();
            } else if let Some((centers, weights)) = step.nearest_centroid() {
                let (centers, weights, guards) =
                    constant_args(centers, weights, step.input_guards());
                let mut args = features.clone();
                args.extend([lit(centers), lit(weights), lit(guards)]);
                label = Some(nearest_centroid_udf().call(args));
            }
        }
        let Some(label) = label else {
            return plan_err!("Predict has no predictor step to lower");
        };
        let mut columns: Vec<Expr> = predict
            .input
            .schema()
            .columns()
            .into_iter()
            .map(Expr::Column)
            .collect();
        columns.push(label.alias(&predict.output));
        let lowered = LogicalPlanBuilder::from(predict.input.clone())
            .project(columns)?
            .build()?;
        Ok(Transformed::yes(lowered))
    }
}
