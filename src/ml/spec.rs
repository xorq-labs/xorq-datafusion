//! Serde types for the pipeline spec v0 exchanged with the Python frontend.
//!
//! - fit request: [`FitRequest`] (`features` plus unfitted [`StepSpec`]s)
//! - fit result: [`FitResult`] (one [`FittedStep`] per step)
//! - compile request: [`CompileRequest`] (`features` plus [`FittedStep`]s)
//!
//! Features are separate `Float64` columns named in `features`; there is no
//! vector packing. Parsing rejects unknown fields; `validate` then checks
//! shapes and ranges, naming the offending field (`steps[1].init`, ...).

use datafusion::common::plan_datafusion_err;
use datafusion::error::{DataFusionError, Result};
use serde::{Deserialize, Serialize};

/// An unfitted step of a fit request.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", deny_unknown_fields)]
pub(crate) enum StepSpec {
    #[serde(rename = "standard_scaler")]
    StandardScaler { with_mean: bool, with_std: bool },
    #[serde(rename = "kmeans")]
    KMeans {
        n_clusters: usize,
        /// Initial centroids, `n_clusters` rows of one value per feature.
        init: Vec<Vec<f64>>,
        max_iter: usize,
        /// Relative tolerance, scaled by the mean feature variance as
        /// scikit-learn does.
        tol: f64,
    },
}

/// A fitted step: what a fit produces and what a compile consumes.
///
/// Scaler vectors are `None` exactly where scikit-learn leaves the attribute
/// `None`: `scale` without `with_std`; `var` without `with_std`; `mean` when
/// neither flag is set.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", deny_unknown_fields)]
pub(crate) enum FittedStep {
    #[serde(rename = "standard_scaler")]
    StandardScaler {
        with_mean: bool,
        with_std: bool,
        mean: Option<Vec<f64>>,
        var: Option<Vec<f64>>,
        scale: Option<Vec<f64>>,
        n_samples_seen: u64,
    },
    #[serde(rename = "kmeans")]
    KMeans {
        cluster_centers: Vec<Vec<f64>>,
        inertia: f64,
        n_iter: usize,
    },
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct FitRequest {
    pub(crate) features: Vec<String>,
    pub(crate) steps: Vec<StepSpec>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct FitResult {
    pub(crate) steps: Vec<FittedStep>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct CompileRequest {
    pub(crate) features: Vec<String>,
    pub(crate) steps: Vec<FittedStep>,
}

fn invalid(field: &str, msg: impl std::fmt::Display) -> DataFusionError {
    plan_datafusion_err!("invalid ML spec: {field}: {msg}")
}

fn parse<T: for<'de> Deserialize<'de>>(json: &str, what: &str) -> Result<T> {
    serde_json::from_str(json).map_err(|e| plan_datafusion_err!("invalid ML {what}: {e}"))
}

fn validate_features(features: &[String]) -> Result<()> {
    if features.is_empty() {
        return Err(invalid("features", "must name at least one column"));
    }
    for (i, name) in features.iter().enumerate() {
        if name.is_empty() {
            return Err(invalid(&format!("features[{i}]"), "empty column name"));
        }
        if features[..i].contains(name) {
            return Err(invalid(
                &format!("features[{i}]"),
                format!("duplicate column {name:?}"),
            ));
        }
    }
    Ok(())
}

fn validate_vector(field: &str, values: &[f64], n_features: usize) -> Result<()> {
    if values.len() != n_features {
        return Err(invalid(
            field,
            format!(
                "expected {n_features} values (one per feature), got {}",
                values.len()
            ),
        ));
    }
    if let Some(j) = values.iter().position(|v| !v.is_finite()) {
        return Err(invalid(&format!("{field}[{j}]"), "must be finite"));
    }
    Ok(())
}

fn validate_matrix(field: &str, rows: &[Vec<f64>], n_rows: usize, n_features: usize) -> Result<()> {
    if rows.len() != n_rows {
        return Err(invalid(
            field,
            format!("expected {n_rows} rows, got {}", rows.len()),
        ));
    }
    rows.iter()
        .enumerate()
        .try_for_each(|(i, row)| validate_vector(&format!("{field}[{i}]"), row, n_features))
}

/// The last step may be a predictor (KMeans); every earlier step must be a
/// transformer.
fn validate_order(kinds: impl Iterator<Item = bool>, n_steps: usize) -> Result<()> {
    for (i, is_predictor) in kinds.enumerate() {
        if is_predictor && i + 1 != n_steps {
            return Err(invalid(
                &format!("steps[{i}]"),
                "kmeans must be the last step",
            ));
        }
    }
    Ok(())
}

impl StepSpec {
    fn validate(&self, field: &str, n_features: usize) -> Result<()> {
        match self {
            StepSpec::StandardScaler { .. } => Ok(()),
            StepSpec::KMeans {
                n_clusters,
                init,
                max_iter,
                tol,
            } => {
                if *n_clusters == 0 {
                    return Err(invalid(
                        &format!("{field}.n_clusters"),
                        "must be at least 1",
                    ));
                }
                if *max_iter == 0 {
                    return Err(invalid(&format!("{field}.max_iter"), "must be at least 1"));
                }
                if !(tol.is_finite() && *tol >= 0.0) {
                    return Err(invalid(&format!("{field}.tol"), "must be finite and >= 0"));
                }
                validate_matrix(&format!("{field}.init"), init, *n_clusters, n_features)
            }
        }
    }
}

impl FittedStep {
    fn validate(&self, field: &str, n_features: usize) -> Result<()> {
        match self {
            FittedStep::StandardScaler {
                with_mean,
                with_std,
                mean,
                var,
                scale,
                ..
            } => {
                let expect = [
                    ("mean", mean, *with_mean || *with_std),
                    ("var", var, *with_std),
                    ("scale", scale, *with_std),
                ];
                for (name, value, required) in expect {
                    let f = format!("{field}.{name}");
                    match (value, required) {
                        (Some(v), true) => validate_vector(&f, v, n_features)?,
                        (None, false) => {}
                        (None, true) => return Err(invalid(&f, "required by with_mean/with_std")),
                        (Some(_), false) => {
                            return Err(invalid(&f, "must be null for these with_mean/with_std"))
                        }
                    }
                }
                if let Some(j) = scale.iter().flatten().position(|s| *s <= 0.0) {
                    return Err(invalid(&format!("{field}.scale[{j}]"), "must be > 0"));
                }
                Ok(())
            }
            FittedStep::KMeans {
                cluster_centers,
                inertia,
                ..
            } => {
                if cluster_centers.is_empty() {
                    return Err(invalid(
                        &format!("{field}.cluster_centers"),
                        "must have at least 1 row",
                    ));
                }
                if !(inertia.is_finite() && *inertia >= 0.0) {
                    return Err(invalid(
                        &format!("{field}.inertia"),
                        "must be finite and >= 0",
                    ));
                }
                validate_matrix(
                    &format!("{field}.cluster_centers"),
                    cluster_centers,
                    cluster_centers.len(),
                    n_features,
                )
            }
        }
    }

    fn is_predictor(&self) -> bool {
        matches!(self, FittedStep::KMeans { .. })
    }
}

fn validate_steps<S>(
    steps: &[S],
    n_features: usize,
    check: impl Fn(&S, &str, usize) -> Result<()>,
    is_predictor: impl Fn(&S) -> bool,
) -> Result<()> {
    if steps.is_empty() {
        return Err(invalid("steps", "must contain at least one step"));
    }
    steps
        .iter()
        .enumerate()
        .try_for_each(|(i, s)| check(s, &format!("steps[{i}]"), n_features))?;
    validate_order(steps.iter().map(is_predictor), steps.len())
}

impl FitRequest {
    pub(crate) fn from_json(json: &str) -> Result<Self> {
        let req: Self = parse(json, "fit request")?;
        req.validate()?;
        Ok(req)
    }

    pub(crate) fn validate(&self) -> Result<()> {
        validate_features(&self.features)?;
        validate_steps(
            &self.steps,
            self.features.len(),
            |s, f, n| s.validate(f, n),
            |s| matches!(s, StepSpec::KMeans { .. }),
        )
    }
}

impl FitResult {
    pub(crate) fn from_json(json: &str, n_features: usize) -> Result<Self> {
        let res: Self = parse(json, "fit result")?;
        res.validate(n_features)?;
        Ok(res)
    }

    pub(crate) fn validate(&self, n_features: usize) -> Result<()> {
        validate_steps(
            &self.steps,
            n_features,
            |s, f, n| s.validate(f, n),
            FittedStep::is_predictor,
        )
    }
}

impl CompileRequest {
    pub(crate) fn from_json(json: &str) -> Result<Self> {
        let req: Self = parse(json, "compile request")?;
        req.validate()?;
        Ok(req)
    }

    pub(crate) fn validate(&self) -> Result<()> {
        validate_features(&self.features)?;
        validate_steps(
            &self.steps,
            self.features.len(),
            |s, f, n| s.validate(f, n),
            FittedStep::is_predictor,
        )
    }
}
