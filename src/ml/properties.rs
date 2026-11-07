//! `StepProperties`: the properties of a fitted step that rewrite rules
//! match on, and `PredictStep`, the form fitted steps take inside a
//! `Predict` node.
//!
//! Rules ask "is this step diagonal-affine?", never "is this a
//! StandardScaler?", so any future step with the same property is rewritten
//! the same way.

use std::cmp::Ordering;
use std::fmt;
use std::hash::{Hash, Hasher};

use super::spec::FittedStep;

/// What rules may rely on about a step.
pub(crate) trait StepProperties {
    /// `Some((shift, scale))` when the step maps each feature independently
    /// as `y_j = (x_j - shift_j) / scale_j`.
    fn diagonal_affine(&self) -> Option<(&[f64], &[f64])>;
    /// `Some((centers, weights))` when the step labels a row with the index
    /// of the nearest center under `sum_j weights_j * (x_j - c_kj)^2`, ties
    /// to the lowest index.
    fn nearest_centroid(&self) -> Option<(&[Vec<f64>], &[f64])>;
    /// The step's output is a linear (affine) function of its input.
    fn is_linear(&self) -> bool;
    /// The step's output for a row depends on that row alone.
    fn is_row_wise(&self) -> bool;
}

/// A fitted step as `Predict` carries it. Equality, hashing and order all
/// compare the numbers' bit patterns, so they agree with each other (`0.0`
/// and `-0.0` differ; a NaN equals itself).
#[derive(Debug, Clone)]
pub(crate) enum PredictStep {
    DiagonalAffine {
        shift: Vec<f64>,
        scale: Vec<f64>,
    },
    NearestCentroid {
        centers: Vec<Vec<f64>>,
        weights: Vec<f64>,
    },
}

impl PredictStep {
    /// The fitted step as a predict step; `n_features` sizes the identity
    /// parts of a scaler fitted without `with_mean`/`with_std`.
    pub(crate) fn from_fitted(step: &FittedStep, n_features: usize) -> Self {
        match step {
            FittedStep::StandardScaler {
                with_mean,
                with_std,
                mean,
                scale,
                ..
            } => PredictStep::DiagonalAffine {
                shift: match (with_mean, mean) {
                    (true, Some(mean)) => mean.clone(),
                    _ => vec![0.0; n_features],
                },
                scale: match (with_std, scale) {
                    (true, Some(scale)) => scale.clone(),
                    _ => vec![1.0; n_features],
                },
            },
            FittedStep::KMeans {
                cluster_centers, ..
            } => PredictStep::NearestCentroid {
                centers: cluster_centers.clone(),
                weights: vec![1.0; n_features],
            },
        }
    }

    /// Bit patterns of every number, in order: equality, hashing and order
    /// over floats that need to be total.
    fn bits(&self) -> (u8, Vec<u64>) {
        let bits = |v: &[f64]| v.iter().map(|x| x.to_bits()).collect::<Vec<_>>();
        match self {
            PredictStep::DiagonalAffine { shift, scale } => {
                (0, [bits(shift), bits(scale)].concat())
            }
            PredictStep::NearestCentroid { centers, weights } => {
                let mut all: Vec<u64> = centers.iter().flat_map(|c| bits(c)).collect();
                all.push(centers.len() as u64);
                all.extend(bits(weights));
                (1, all)
            }
        }
    }
}

impl PartialEq for PredictStep {
    fn eq(&self, other: &Self) -> bool {
        self.bits() == other.bits()
    }
}

impl Eq for PredictStep {}

impl Hash for PredictStep {
    fn hash<H: Hasher>(&self, state: &mut H) {
        self.bits().hash(state)
    }
}

impl PartialOrd for PredictStep {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        Some(self.bits().cmp(&other.bits()))
    }
}

impl fmt::Display for PredictStep {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            PredictStep::DiagonalAffine { shift, .. } => {
                write!(f, "diagonal_affine(d={})", shift.len())
            }
            PredictStep::NearestCentroid { centers, weights } => {
                let d = weights.len();
                let weighted = weights.iter().any(|w| *w != 1.0);
                write!(
                    f,
                    "nearest_centroid(k={}, d={d}{})",
                    centers.len(),
                    if weighted { ", weighted" } else { "" }
                )
            }
        }
    }
}

impl StepProperties for PredictStep {
    fn diagonal_affine(&self) -> Option<(&[f64], &[f64])> {
        match self {
            PredictStep::DiagonalAffine { shift, scale } => Some((shift, scale)),
            PredictStep::NearestCentroid { .. } => None,
        }
    }

    fn nearest_centroid(&self) -> Option<(&[Vec<f64>], &[f64])> {
        match self {
            PredictStep::NearestCentroid { centers, weights } => Some((centers, weights)),
            PredictStep::DiagonalAffine { .. } => None,
        }
    }

    fn is_linear(&self) -> bool {
        matches!(self, PredictStep::DiagonalAffine { .. })
    }

    fn is_row_wise(&self) -> bool {
        true
    }
}
