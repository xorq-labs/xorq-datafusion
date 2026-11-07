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

/// How far, relative to the closest pair of centers, a fused center may
/// drift from the original when mapped back through the affine step.
const FUSION_TOLERANCE: f64 = 1e-9;

/// Smallest Chebyshev distance between two centers (infinite for one).
fn min_separation(centers: &[Vec<f64>]) -> f64 {
    let mut min = f64::INFINITY;
    for (k, a) in centers.iter().enumerate() {
        for b in &centers[k + 1..] {
            let d = a
                .iter()
                .zip(b)
                .map(|(x, y)| (x - y).abs())
                .fold(0.0, f64::max);
            min = min.min(d);
        }
    }
    min
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
    // Fusion changes the arithmetic. Keep the original steps when that
    // change is not negligible: a weight or center that is not finite (tiny
    // or huge scales), or centers that no longer map back to the originals
    // closely compared with how far apart the centers are (large shifts lose
    // the low bits of `scale * c`).
    if fused_weights.iter().any(|w| !(w.is_finite() && *w > 0.0)) {
        return None;
    }
    let mut drift = 0.0_f64;
    for (fused, original) in fused_centers.iter().zip(centers) {
        for j in 0..original.len() {
            if !fused[j].is_finite() {
                return None;
            }
            drift = drift.max(((fused[j] - shift[j]) / scale[j] - original[j]).abs());
        }
    }
    if drift > FUSION_TOLERANCE * min_separation(centers) {
        return None;
    }
    Some(PredictStep::NearestCentroid {
        centers: fused_centers,
        weights: fused_weights,
    })
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
                let (centers, weights) = constant_args(centers, weights);
                let mut args = features.clone();
                args.extend([lit(centers), lit(weights)]);
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
