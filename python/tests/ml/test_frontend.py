import copy
import json

import numpy as np
import pyarrow as pa
import pytest
from sklearn.cluster import KMeans
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import MinMaxScaler, StandardScaler

import xorq_datafusion.ml as ml
from xorq_datafusion._internal import ml as _native
from xorq_datafusion.ml import Reason, Supported, Unsupported
from xorq_datafusion.ml.frontend import (
    UnsupportedError,
    apply_fit_result,
    default_features,
    to_compile_spec,
    to_fit_spec,
)

FEATURES = ["x0", "x1", "x2"]


@pytest.fixture
def X():
    rng = np.random.default_rng(0)
    centers = np.array([[0.0, 0.0, 0.0], [10.0, 10.0, 0.0], [0.0, 10.0, 10.0]])
    return np.vstack([c + rng.normal(size=(50, 3)) for c in centers])


@pytest.fixture
def init():
    return np.array([[1.0, 1.0, 1.0], [9.0, 9.0, 1.0], [1.0, 9.0, 9.0]])


def pipeline(c0, with_mean=True, with_std=True, **kmeans):
    params = {"init": c0, "n_init": 1} | kmeans
    return make_pipeline(
        StandardScaler(with_mean=with_mean, with_std=with_std),
        KMeans(n_clusters=len(c0), **params),
    )


# --- supports ---------------------------------------------------------------


def test_supports_target_pipeline(init):
    assert ml.supports(pipeline(init)) == Supported()
    assert ml.supports(pipeline(init, n_init="auto"))


@pytest.mark.parametrize(
    ("make", "reason"),
    [
        (lambda init: KMeans(3, init=init, n_init=1), Reason.UNSUPPORTED_ESTIMATOR),
        (
            lambda init: make_pipeline(StandardScaler()),
            Reason.UNSUPPORTED_PIPELINE_SHAPE,
        ),
        (
            lambda init: make_pipeline(
                KMeans(3, init=init, n_init=1), StandardScaler()
            ),
            Reason.UNSUPPORTED_PIPELINE_SHAPE,
        ),
        (
            lambda init: make_pipeline(MinMaxScaler(), KMeans(3, init=init, n_init=1)),
            Reason.UNSUPPORTED_PIPELINE_SHAPE,
        ),
        (
            lambda init: pipeline(init, init="k-means++"),
            Reason.UNSUPPORTED_PARAMETER,
        ),
        (
            lambda init: pipeline(init, init=lambda X, k, random_state: init),
            Reason.UNSUPPORTED_PARAMETER,
        ),
        (lambda init: pipeline(init, init=init[:2]), Reason.UNSUPPORTED_PARAMETER),
        (lambda init: pipeline(init, n_init=3), Reason.UNSUPPORTED_PARAMETER),
        (lambda init: pipeline(init, algorithm="elkan"), Reason.UNSUPPORTED_PARAMETER),
    ],
    ids=[
        "bare-kmeans",
        "scaler-only",
        "reversed",
        "other-scaler",
        "init-string",
        "init-callable",
        "init-shape",
        "n_init",
        "algorithm",
    ],
)
def test_supports_rejects(init, make, reason):
    verdict = ml.supports(make(init))
    assert isinstance(verdict, Unsupported)
    assert not verdict
    assert verdict.reason is reason
    assert verdict.detail


def test_reasons_include_fine_grained_mutation():
    assert Reason.NEEDS_FINE_GRAINED_MUTATION.value == "needs fine-grained mutation"


def test_unsupported_pipeline_is_refused_by_specs(init):
    with pytest.raises(UnsupportedError, match="unsupported parameter") as info:
        to_fit_spec(pipeline(init, n_init=3), FEATURES)
    assert info.value.unsupported.reason is Reason.UNSUPPORTED_PARAMETER


# --- features ---------------------------------------------------------------


def test_default_features_are_numeric_columns_in_order():
    schema = pa.schema(
        [
            ("a", pa.float64()),
            ("name", pa.string()),
            ("b", pa.int32()),
            ("flag", pa.bool_()),
            ("c", pa.float32()),
        ]
    )
    assert default_features(schema) == ["a", "b", "c"]


def test_feature_count_must_match(init):
    with pytest.raises(ValueError, match="expected 3 columns, got 2"):
        to_fit_spec(pipeline(init), FEATURES[:2])


# --- fit spec ---------------------------------------------------------------


def test_fit_spec(init):
    spec = to_fit_spec(pipeline(init, tol=1e-3, max_iter=50), FEATURES)
    assert spec == {
        "features": FEATURES,
        "steps": [
            {"kind": "standard_scaler", "with_mean": True, "with_std": True},
            {
                "kind": "kmeans",
                "n_clusters": 3,
                "init": init.tolist(),
                "max_iter": 50,
                "tol": 1e-3,
            },
        ],
    }
    assert json.loads(_native.validate_fit_request(json.dumps(spec))) == spec


# --- compile spec and fit-result round trip -----------------------------------


@pytest.mark.parametrize(
    ("with_mean", "with_std"),
    [(True, True), (False, True), (True, False), (False, False)],
)
def test_round_trip_through_specs_predicts_like_sklearn(X, init, with_mean, with_std):
    fitted = pipeline(init, with_mean, with_std).fit(X)
    spec = to_compile_spec(fitted, FEATURES)
    assert json.loads(_native.validate_compile_request(json.dumps(spec))) == spec

    fresh = pipeline(init, with_mean, with_std)
    apply_fit_result(fresh, {"steps": spec["steps"]})

    np.testing.assert_array_equal(fresh.predict(X), fitted.predict(X))
    # KMeans.transform is a BLAS distance; it may differ in the last ulps
    # between equal center arrays at different addresses.
    np.testing.assert_allclose(fresh.transform(X), fitted.transform(X), rtol=1e-12)
    np.testing.assert_array_equal(fresh[0].transform(X), fitted[0].transform(X))
    for attr in ("mean_", "var_", "scale_", "n_samples_seen_", "n_features_in_"):
        np.testing.assert_array_equal(getattr(fresh[0], attr), getattr(fitted[0], attr))
    for attr in ("cluster_centers_", "inertia_", "n_iter_", "n_features_in_"):
        np.testing.assert_array_equal(getattr(fresh[1], attr), getattr(fitted[1], attr))


def test_compile_spec_requires_fitted(init):
    with pytest.raises(Exception, match="not fitted"):
        to_compile_spec(pipeline(init), FEATURES)


def test_apply_fit_result_refuses_mismatched_flags(X, init):
    spec = to_compile_spec(pipeline(init).fit(X), FEATURES)
    with pytest.raises(ValueError, match="with_mean/with_std"):
        apply_fit_result(pipeline(init, with_mean=False), {"steps": spec["steps"]})


def test_apply_fit_result_refuses_wrong_cluster_count(X, init):
    spec = to_compile_spec(pipeline(init).fit(X), FEATURES)
    steps = copy.deepcopy(spec["steps"])
    steps[1]["cluster_centers"] = steps[1]["cluster_centers"][:2]
    with pytest.raises(ValueError, match="expected 3 cluster centers"):
        apply_fit_result(pipeline(init), {"steps": steps})


# --- native validation names the offending field --------------------------------


def _fit_request(**kmeans):
    step = {
        "kind": "kmeans",
        "n_clusters": 2,
        "init": [[0.0, 0.0], [1.0, 1.0]],
        "max_iter": 10,
        "tol": 0.0,
    } | kmeans
    return {
        "features": ["a", "b"],
        "steps": [
            {"kind": "standard_scaler", "with_mean": True, "with_std": True},
            step,
        ],
    }


def _fitted_scaler(**fields):
    return {
        "kind": "standard_scaler",
        "with_mean": True,
        "with_std": True,
        "mean": [0.0, 0.0],
        "var": [1.0, 1.0],
        "scale": [1.0, 1.0],
        "n_samples_seen": 4,
    } | fields


def _compile_request(**scaler):
    kmeans = {
        "kind": "kmeans",
        "cluster_centers": [[0.0, 0.0]],
        "inertia": 0.0,
        "n_iter": 1,
    }
    return {"features": ["a", "b"], "steps": [_fitted_scaler(**scaler), kmeans]}


@pytest.mark.parametrize(
    ("spec", "match"),
    [
        ({"features": ["a"]}, "missing field `steps`"),
        (_fit_request() | {"extra": 1}, "unknown field `extra`"),
        (
            {"features": ["a"], "steps": [{"kind": "pca"}]},
            "unknown variant `pca`",
        ),
        ({"features": [], "steps": _fit_request()["steps"]}, "features: must name"),
        (
            {"features": ["a", "a"], "steps": _fit_request()["steps"]},
            r"features\[1\]: duplicate",
        ),
        ({"features": ["a", "b"], "steps": []}, "steps: must contain"),
        (_fit_request(n_clusters=0), r"steps\[1\].n_clusters"),
        (_fit_request(max_iter=0), r"steps\[1\].max_iter"),
        (_fit_request(tol=-1.0), r"steps\[1\].tol"),
        (_fit_request(init=[[0.0, 0.0]]), r"steps\[1\].init: expected 2 rows"),
        (
            _fit_request(init=[[0.0, 0.0], [1.0]]),
            r"steps\[1\].init\[1\]: expected 2 values",
        ),
        (
            {
                "features": ["a", "b"],
                "steps": list(reversed(_fit_request()["steps"])),
            },
            r"steps\[0\]: kmeans must be the last step",
        ),
    ],
    ids=[
        "missing-steps",
        "unknown-field",
        "unknown-kind",
        "no-features",
        "duplicate-feature",
        "no-steps",
        "n_clusters",
        "max_iter",
        "tol",
        "init-rows",
        "init-row-width",
        "kmeans-not-last",
    ],
)
def test_fit_request_validation(spec, match):
    with pytest.raises(ValueError, match=match):
        _native.validate_fit_request(json.dumps(spec))


@pytest.mark.parametrize(
    ("spec", "match"),
    [
        (_compile_request(scale=[1.0, 0.0]), r"steps\[0\].scale\[1\]: must be > 0"),
        (_compile_request(var=None), r"steps\[0\].var: required"),
        (
            _compile_request(with_std=False),
            r"steps\[0\].var: must be null",
        ),
        (
            _compile_request(with_mean=False, with_std=False, var=None, scale=None),
            r"steps\[0\].mean: must be null",
        ),
        (_compile_request(mean=[0.0]), r"steps\[0\].mean: expected 2 values"),
    ],
    ids=["scale-zero", "var-missing", "var-not-null", "mean-not-null", "mean-width"],
)
def test_compile_request_validation(spec, match):
    with pytest.raises(ValueError, match=match):
        _native.validate_compile_request(json.dumps(spec))


def test_fit_result_validation_checks_feature_count():
    result = {"steps": _compile_request()["steps"]}
    _native.validate_fit_result(json.dumps(result), 2)
    with pytest.raises(ValueError, match=r"steps\[0\].mean: expected 3 values"):
        _native.validate_fit_result(json.dumps(result), 3)


def test_apply_fit_result_clears_state_of_an_earlier_fit(X, init):
    pd = pytest.importorskip("pandas")
    spec = to_compile_spec(pipeline(init).fit(X), FEATURES)
    reused = pipeline(init).fit(pd.DataFrame(X, columns=["a", "b", "c"]))
    assert hasattr(reused[1], "labels_")

    apply_fit_result(reused, {"steps": spec["steps"]})

    for step in reused:
        assert not hasattr(step, "feature_names_in_")
    assert not hasattr(reused[1], "labels_")
    renamed = pd.DataFrame(X, columns=["d", "e", "f"])
    # Like a scikit-learn fit on an unnamed array: names are not checked.
    with pytest.warns(UserWarning, match="fitted without feature names"):
        labels = reused.predict(renamed)
    np.testing.assert_array_equal(labels, reused.predict(X))


def test_compile_spec_rejects_fractional_sample_count(X, init):
    weights = np.full(len(X), 0.5)
    fitted = pipeline(init).fit(
        X, standardscaler__sample_weight=[*weights[:-1].tolist(), 1.0]
    )
    assert fitted[0].n_samples_seen_ != int(fitted[0].n_samples_seen_)
    with pytest.raises(ValueError, match="one whole count"):
        to_compile_spec(fitted, FEATURES)


def test_compile_spec_rejects_per_feature_sample_counts(X, init):
    X_nan = X.copy()
    X_nan[0, 0] = np.nan
    fitted = pipeline(init)
    fitted[0].fit(X_nan)
    fitted[1].fit(np.nan_to_num(fitted[0].transform(X_nan)))
    assert np.ndim(fitted[0].n_samples_seen_) == 1
    with pytest.raises(ValueError, match="one whole count"):
        to_compile_spec(fitted, FEATURES)


def test_compile_spec_upcasts_float32_fit_losslessly(X, init):
    fitted = pipeline(init).fit(X.astype(np.float32))
    assert fitted[1].cluster_centers_.dtype == np.float32
    spec = to_compile_spec(fitted, FEATURES)
    centers = np.asarray(spec["steps"][1]["cluster_centers"])
    assert centers.dtype == np.float64
    np.testing.assert_array_equal(
        centers.astype(np.float32), fitted[1].cluster_centers_
    )
