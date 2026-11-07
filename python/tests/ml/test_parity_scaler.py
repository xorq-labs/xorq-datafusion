import json

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from sklearn.cluster import KMeans
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

import xorq_datafusion.ml as ml
from xorq_datafusion import SessionContext
from xorq_datafusion._internal import ml as _native
from xorq_datafusion.ml.frontend import to_fit_spec

RTOL, ATOL = 1e-7, 1e-9
N_PARTITIONS = 4


def blobs(rng):
    centers = np.array([[0.0, 0.0, 0.0], [5.0, 5.0, -3.0], [-4.0, 6.0, 2.0]])
    return np.vstack([c + rng.normal(size=(400, 3)) for c in centers])


def offset_small_variance(rng):
    # A large mean over a tiny spread: the case naive sum-of-squares gets wrong.
    return 1e6 + rng.normal(scale=1e-2, size=(1000, 3))


def constant_and_integer(rng):
    return np.column_stack(
        [
            rng.normal(size=1000),
            np.full(1000, 7.25),  # zero variance: scale must be 1.0
            rng.integers(-50, 50, size=1000),  # stored as int64 below
        ]
    )


DATASETS = {
    "blobs": blobs,
    "offset_small_variance": offset_small_variance,
    "constant_and_integer": constant_and_integer,
}


def to_table(X, name):
    columns = {f"x{j}": X[:, j] for j in range(X.shape[1])}
    if name == "constant_and_integer":
        columns["x2"] = X[:, 2].astype(np.int64)
    return pa.table(columns)


def register(ctx, how, table, tmp_path):
    batches = table.to_batches(max_chunksize=-(-table.num_rows // N_PARTITIONS))
    if how == "record_batches":
        ctx.register_record_batches("t", [[b] for b in batches])
    elif how == "record_batch_reader":
        ctx.register_record_batch_reader(
            "t", pa.RecordBatchReader.from_batches(table.schema, batches)
        )
    else:
        path = tmp_path / "t.parquet"
        pq.write_table(table, path, row_group_size=len(batches[0]))
        ctx.register_parquet("t", [str(path)])
    return ctx.table("t")


def native_scaler(df, features, **flags):
    init = np.zeros((1, len(features)))
    spec = to_fit_spec(
        make_pipeline(StandardScaler(**flags), KMeans(1, init=init, n_init=1)),
        features,
    )
    spec["steps"] = spec["steps"][:1]  # scaler only
    return json.loads(_native.fit(df, json.dumps(spec)))["steps"][0]


def assert_matches_sklearn(fitted, X, **flags):
    expected = StandardScaler(**flags).fit(X)
    assert fitted["n_samples_seen"] == expected.n_samples_seen_
    for attr in ("mean", "var", "scale"):
        actual, want = fitted[attr], getattr(expected, f"{attr}_")
        if want is None:
            assert actual is None, attr
        else:
            np.testing.assert_allclose(actual, want, rtol=RTOL, atol=ATOL, err_msg=attr)


@pytest.mark.parametrize("how", ["record_batches", "record_batch_reader", "parquet"])
@pytest.mark.parametrize("dataset", DATASETS)
def test_scaler_fit_matches_sklearn(ctx, tmp_path, how, dataset):
    X = DATASETS[dataset](np.random.default_rng(0))
    df = register(ctx, how, to_table(X, dataset), tmp_path)
    assert_matches_sklearn(native_scaler(df, ["x0", "x1", "x2"]), X)


@pytest.mark.parametrize(
    "flags",
    [
        {"with_mean": False},
        {"with_std": False},
        {"with_mean": False, "with_std": False},
    ],
    ids=["no-mean", "no-std", "neither"],
)
def test_scaler_fit_flags(ctx, tmp_path, flags):
    X = constant_and_integer(np.random.default_rng(1))
    df = register(ctx, "record_batches", to_table(X, "constant_and_integer"), tmp_path)
    assert_matches_sklearn(native_scaler(df, ["x0", "x1", "x2"], **flags), X, **flags)


def test_scaler_fit_builds_on_any_dataframe(ctx, tmp_path):
    X = blobs(np.random.default_rng(2))
    register(ctx, "record_batches", to_table(X, "blobs"), tmp_path)
    df = ctx.sql("SELECT x2 AS c, x0 AS a FROM t WHERE x1 > 0")
    kept = X[X[:, 1] > 0][:, [2, 0]]
    assert_matches_sklearn(native_scaler(df, ["c", "a"]), kept)


@pytest.mark.parametrize(
    "columns",
    [
        {"a": [1.0, None, 3.0], "b": [1.0, 2.0, 3.0]},
        {"a": [1.0, None, 3.0]},
        {"a": [1.0, None, 3.0], "b": [None, 2.0, 3.0]},
    ],
    ids=["one-of-two", "single-feature", "equal-null-counts"],
)
def test_scaler_fit_refuses_missing_values(ctx, columns):
    ctx.register_record_batches("t", [pa.table(columns).to_batches()])
    with pytest.raises(ValueError, match="missing values are not supported"):
        native_scaler(ctx.table("t"), list(columns))


@pytest.mark.parametrize("bad", [np.nan, np.inf, -np.inf])
def test_scaler_fit_refuses_non_finite_values(ctx, bad):
    ctx.register_record_batches("t", [[pa.record_batch({"a": [1.0, bad, 3.0]})]])
    with pytest.raises(ValueError, match="NaN or infinite"):
        native_scaler(ctx.table("t"), ["a"])


def test_scaler_fit_merge_does_not_overflow(ctx):
    # Two partitions, 1e4 copies each of -1e150 and +1e150: M2 = 2e304 is
    # finite, but delta^2 * n_a * n_b would be 4e308.
    halves = [pa.record_batch({"a": np.full(10_000, sign * 1e150)}) for sign in (-1, 1)]
    ctx.register_record_batches("t", [[half] for half in halves])
    fitted = native_scaler(ctx.table("t"), ["a"])
    np.testing.assert_allclose(fitted["var"], [1e300], rtol=RTOL)
    np.testing.assert_allclose(fitted["scale"], [1e150], rtol=RTOL)
    # The exact mean is 0; merge order leaves rounding relative to |x| = 1e150.
    assert abs(fitted["mean"][0]) <= 1e150 * 1e-12


def test_scaler_fit_merge_does_not_overflow_when_squaring(ctx):
    # Singleton partitions of -+7e153: delta^2 = 1.96e308 overflows, while
    # M2 = 9.8e307 and var = 4.9e307 are finite.
    ctx.register_record_batches(
        "t", [[pa.record_batch({"a": [sign * 7e153]})] for sign in (-1, 1)]
    )
    fitted = native_scaler(ctx.table("t"), ["a"])
    np.testing.assert_allclose(fitted["var"], [4.9e307], rtol=RTOL)
    np.testing.assert_allclose(fitted["scale"], [np.sqrt(4.9e307)], rtol=RTOL)


def test_native_fit_refuses_chained_scalers(ctx):
    ctx.register_record_batches("t", [[pa.record_batch({"a": [1.0, 3.0]})]])
    scaler = {"kind": "standard_scaler", "with_mean": True, "with_std": True}
    request = {"features": ["a"], "steps": [scaler, scaler]}
    with pytest.raises(ValueError, match=r"steps\[1\]: a standard_scaler after"):
        _native.fit(ctx.table("t"), json.dumps(request))


def test_scaler_fit_refuses_empty_input(ctx):
    ctx.register_record_batches(
        "t", [[pa.record_batch({"a": pa.array([], pa.float64())})]]
    )
    with pytest.raises(ValueError, match="no rows"):
        native_scaler(ctx.table("t"), ["a"])


def test_ml_fit_stops_at_kmeans_until_its_fit_lands(ctx, tmp_path):
    X = blobs(np.random.default_rng(3))
    df = register(ctx, "record_batches", to_table(X, "blobs"), tmp_path)
    pipeline = make_pipeline(StandardScaler(), KMeans(2, init=X[:2], n_init=1))
    with pytest.raises(ValueError, match="KMeans fit is not implemented"):
        ml.fit(pipeline, df)


def test_welford_is_registered_under_ml_name():
    ctx = SessionContext()  # default config: information_schema on
    names = ctx.sql("SHOW FUNCTIONS LIKE '__ml_%'").to_arrow_table()
    assert "__ml_welford" in names.column("function_name").to_pylist()
