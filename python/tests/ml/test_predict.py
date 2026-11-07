import time

import numpy as np
import pyarrow as pa
import pytest
from sklearn.cluster import KMeans
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

import xorq_datafusion.ml as ml
from xorq_datafusion._internal import ml as _native

FEATURES = ["x0", "x1", "x2"]


def blobs(seed=0, n_per_cluster=250):
    rng = np.random.default_rng(seed)
    centers = np.array(
        [[0.0, 0.0, 0.0], [8.0, 8.0, 0.0], [0.0, 8.0, 8.0], [8.0, 0.0, 8.0]]
    )
    X = np.vstack([c + rng.normal(size=(n_per_cluster, 3)) for c in centers])
    X = X[rng.permutation(len(X))]
    init = StandardScaler().fit_transform(X)[[0, 1, 2, 3]]
    return X, init


def sklearn_pipeline(init, **scaler):
    return make_pipeline(
        StandardScaler(**scaler), KMeans(len(init), init=init, n_init=1)
    )


def register(ctx, X, name="t", extra=None):
    columns = {f: X[:, j] for j, f in enumerate(FEATURES)} | (
        extra or {"id": np.arange(len(X))}
    )
    table = pa.table(columns)
    ctx.register_record_batches(
        name, [[b] for b in table.to_batches(max_chunksize=250)]
    )
    return ctx.table(name)


def labels_in_row_order(df):
    """Labels ordered by ``id``: partitions may return rows in any order."""
    return df.to_arrow_table().sort_by("id").column("label")


@pytest.mark.parametrize(
    "scaler",
    [
        {},
        {"with_mean": False},
        {"with_std": False},
        {"with_mean": False, "with_std": False},
    ],
    ids=["default", "no-mean", "no-std", "neither"],
)
def test_predict_matches_sklearn_exactly(ctx, scaler):
    X, init = blobs()
    fitted = sklearn_pipeline(init, **scaler).fit(X)
    model = ml.compile(fitted, FEATURES)
    labels = labels_in_row_order(model.predict(register(ctx, X)))
    assert labels.type == pa.int64()
    np.testing.assert_array_equal(labels.to_numpy(), fitted.predict(X))


def test_predict_after_native_fit_uses_dataframe_features(ctx):
    X, init = blobs(1)
    register(ctx, X)
    df = ctx.sql("SELECT x0, x1, x2 FROM t")  # numeric columns = the features
    fitted = ml.fit(sklearn_pipeline(init), df)
    model = ml.compile(fitted)
    assert model.features is None
    out = model.predict(df).to_arrow_table()
    X_seen = np.column_stack([out.column(f).to_numpy() for f in FEATURES])
    np.testing.assert_array_equal(
        out.column("label").to_numpy(), fitted.predict(X_seen)
    )


def test_predict_keeps_input_columns_and_rows(ctx):
    X, init = blobs(2)
    ids = np.arange(len(X))
    df = register(ctx, X, extra={"id": ids, "tag": [f"r{i}" for i in ids]})
    out = (
        ml.compile(sklearn_pipeline(init).fit(X), FEATURES).predict(df).to_arrow_table()
    )
    assert out.column_names == [*FEATURES, "id", "tag", "label"]
    assert sorted(out.column("id").to_pylist()) == ids.tolist()


def test_predict_composes_with_sql(ctx):
    X, init = blobs(3)
    fitted = sklearn_pipeline(init).fit(X)
    expected = fitted.predict(X)
    ids = np.arange(len(X))
    predicted = ml.compile(fitted, FEATURES).predict(
        register(ctx, X, extra={"id": ids})
    )
    ctx.register_dataframe("p", predicted)

    counts = ctx.sql("SELECT label, count(*) AS n FROM p GROUP BY label ORDER BY label")
    assert (
        counts.to_arrow_table().column("n").to_pylist()
        == np.bincount(expected).tolist()
    )

    threes = ctx.sql("SELECT id FROM p WHERE label = 3 ORDER BY id").to_arrow_table()
    assert threes.column("id").to_pylist() == ids[expected == 3].tolist()

    ctx.register_record_batches(
        "names",
        [[pa.record_batch({"label": [0, 1, 2, 3], "name": ["a", "b", "c", "d"]})]],
    )
    joined = ctx.sql(
        "SELECT name, count(*) AS n FROM p JOIN names USING (label) GROUP BY name ORDER BY name"
    )
    assert (
        joined.to_arrow_table().column("n").to_pylist()
        == np.bincount(expected).tolist()
    )


def test_predict_on_sql_dataframe(ctx):
    X, init = blobs(4)
    fitted = sklearn_pipeline(init).fit(X)
    register(ctx, X)
    df = ctx.sql("SELECT id, x0, x1, x2 FROM t WHERE x0 > 4")
    labels = labels_in_row_order(ml.compile(fitted, FEATURES).predict(df))
    np.testing.assert_array_equal(labels.to_numpy(), fitted.predict(X[X[:, 0] > 4]))


def test_null_or_non_finite_features_get_null_labels(ctx):
    X, init = blobs(5)
    fitted = sklearn_pipeline(init).fit(X)
    table = pa.table(
        {
            "x0": pa.array([0.0, None, float("nan"), 8.0], pa.float64()),
            "x1": [0.0, 0.0, 0.0, 8.0],
            "x2": [0.0, 0.0, 0.0, 0.0],
        }
    )
    ctx.register_record_batches("t", [table.to_batches()])
    labels = ml.compile(fitted, FEATURES).predict(ctx.table("t")).to_arrow_table()
    assert labels.column("label").to_pylist()[1:3] == [None, None]
    assert labels.column("label").to_pylist()[0] == fitted.predict([[0.0, 0.0, 0.0]])[0]


def test_predict_refuses_mismatched_features(ctx):
    X, init = blobs(6)
    fitted = sklearn_pipeline(init).fit(X)
    df = register(ctx, X, extra={"y": X[:, 0]})
    with pytest.raises(ValueError, match="expects 3 features, got 4"):
        ml.compile(fitted).predict(df)
    with pytest.raises(ValueError, match="not a column"):
        ml.compile(fitted, ["x0", "x1", "nope"]).predict(df)


def test_predict_refuses_existing_label_column(ctx):
    X, init = blobs(7)
    df = register(ctx, X, extra={"label": np.zeros(len(X))})
    with pytest.raises(ValueError, match="already exists"):
        ml.compile(sklearn_pipeline(init).fit(X), FEATURES).predict(df)


def test_explain_stages(ctx):
    X, init = blobs(8)
    model = ml.compile(sklearn_pipeline(init).fit(X), FEATURES)
    assert model.explain("logical").startswith("Predict: features=[x0, x1, x2]")
    assert "__ml_nearest_centroid" in model.explain("optimized")
    assert "Predict" not in model.explain("optimized")
    assert "ProjectionExec" in model.explain("physical")
    assert model.explain("parallel") == "not yet implemented"
    with pytest.raises(ValueError, match="stage must be one of"):
        model.explain("bogus")


def model_from(mean, scale, centers):
    """A Model from exact fitted values (one or more features)."""
    d = len(mean)
    steps = [
        {
            "kind": "standard_scaler",
            "with_mean": True,
            "with_std": True,
            "mean": mean,
            "var": [s * s for s in scale],
            "scale": scale,
            "n_samples_seen": 10,
        },
        {"kind": "kmeans", "cluster_centers": centers, "inertia": 0.0, "n_iter": 1},
    ]
    return ml.Model(steps, [f"x{j}" for j in range(d)])


def fused_plan(model):
    return _native.explain_predict(model._request(model.features), "label", "fused")


@pytest.mark.parametrize(
    ("mean", "scale", "centers", "x", "label"),
    [
        # 2**53 + 3 is not representable: the fused center would round onto
        # 2**53 + 4 and tie with x = 2**53 + 2, whose scaled value 2 is
        # nearest to center 3.
        ([2.0**53], [1.0], [[0.0], [3.0], [-3.0]], 2.0**53 + 2, 1),
        # 1 / scale**2 overflows to inf.
        ([0.0], [1e-200], [[0.0], [1.0]], 0.6e-200, 1),
        # Centers near 2**53 (ulp 2): s + a*c round-trips exactly, yet the
        # fused distances tie where the unfused ones do not.
        ([1.0], [1.0], [[2.0**53 + 8], [2.0**53 + 4]], 2.0**53 + 6, 1),
        # A scale below the safe domain (2**-500): the error bound underflows
        # to 0 there, so only the domain check can refuse it (6v4e).
        ([0.0], [2.0**-511], [[0.7071067811865475 * 2.0**-537], [0.0]], 0.0, 0),
    ],
    ids=["large-shift", "tiny-scale", "large-centers", "subnormal-scale"],
)
def test_fusion_is_skipped_when_it_would_change_labels(
    ctx, mean, scale, centers, x, label
):
    model = model_from(mean, scale, centers)
    assert "weighted" not in fused_plan(model)
    ctx.register_record_batches("t", [[pa.record_batch({"x0": [x], "id": [0]})]])
    assert model.predict(ctx.table("t")).to_arrow_table().column(
        "label"
    ).to_pylist() == [label]


def test_fusion_applies_to_a_fitted_model():
    X, init = blobs(9)
    model = ml.compile(sklearn_pipeline(init).fit(X), FEATURES)
    assert "nearest_centroid(k=4, d=3, weighted)" in fused_plan(model)


def test_fusion_check_is_fast_for_many_centers():
    # Coordinate 0 alone separates the centers by 1: the cheap bound decides.
    k, d = 10_000, 128
    centers = np.random.default_rng(0).normal(size=(k, d))
    centers[:, 0] = np.arange(k)
    model = model_from([0.5] * d, [2.0] * d, centers.tolist())
    start = time.monotonic()
    plan = fused_plan(model)
    assert time.monotonic() - start < 5
    assert f"nearest_centroid(k={k}, d={d}, weighted)" in plan


def test_fusion_check_falls_back_to_pairs():
    # Random centers: no single coordinate separates them all, the pairwise
    # check (within the work cap) does.
    centers = np.random.default_rng(1).normal(size=(500, 32))
    plan = fused_plan(model_from([0.5] * 32, [2.0] * 32, centers.tolist()))
    assert "nearest_centroid(k=500, d=32, weighted)" in plan


def test_fusion_check_gives_up_rather_than_planning_slowly():
    # A grid: every coordinate repeats, so the cheap separation bound is 0 and
    # only the pairwise check could decide; it is far past the work cap.
    k, d = 10_000, 128
    centers = np.zeros((k, d))
    centers[:, 0] = np.arange(k) % 100
    centers[:, 1] = np.arange(k) // 100
    model = model_from([1e6] * d, [1.0] * d, centers.tolist())
    start = time.monotonic()
    plan = fused_plan(model)
    assert time.monotonic() - start < 30
    assert "weighted" not in plan


def test_fused_predict_nulls_rows_whose_unfused_transform_overflows(ctx):
    # (x - 0) / 1e-100 overflows for x = 1e308: the unfused plan labels it
    # null, so the fused one must too (beh5); smaller x still get labels.
    model = model_from([0.0], [1e-100], [[0.0], [1.0]])
    assert "weighted" in fused_plan(model)
    xs = [1e308, -1e308, 0.0, 1e-100]
    ctx.register_record_batches("t", [[pa.record_batch({"x0": xs, "id": range(4)})]])
    labels = labels_in_row_order(model.predict(ctx.table("t"))).to_pylist()
    assert labels == [None, None, 0, 1]
