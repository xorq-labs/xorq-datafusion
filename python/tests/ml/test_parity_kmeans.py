import json

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from sklearn.cluster import KMeans
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

import xorq_datafusion.ml as ml
from xorq_datafusion._internal import ml as _native

RTOL, ATOL = 1e-7, 1e-9
N_PARTITIONS = 4


def blobs(seed, n_per_cluster=300):
    """Well-separated blobs, shuffled, with one initial center per blob.

    The initial centers are taken in the scaled space the KMeans step sees.
    """
    rng = np.random.default_rng(seed)
    centers = np.array(
        [[0.0, 0.0, 0.0], [8.0, 8.0, 0.0], [0.0, 8.0, 8.0], [8.0, 0.0, 8.0]]
    )
    X = np.vstack([c + rng.normal(size=(n_per_cluster, 3)) for c in centers])
    truth = np.repeat(np.arange(len(centers)), n_per_cluster)
    order = rng.permutation(len(X))
    X, truth = X[order], truth[order]
    scaled = StandardScaler().fit_transform(X)
    init = np.array([scaled[np.argmax(truth == k)] for k in range(len(centers))])
    return X, init


def register(ctx, how, X, tmp_path):
    table = pa.table({f"x{j}": X[:, j] for j in range(X.shape[1])})
    batches = table.to_batches(max_chunksize=-(-table.num_rows // N_PARTITIONS))
    if how == "record_batches":
        ctx.register_record_batches("t", [[b] for b in batches])
    else:
        path = tmp_path / "t.parquet"
        pq.write_table(table, path, row_group_size=len(batches[0]))
        ctx.register_parquet("t", [str(path)])
    return ctx.table("t")


def pipeline(init, **kmeans):
    return make_pipeline(
        StandardScaler(), KMeans(len(init), init=init, n_init=1, **kmeans)
    )


@pytest.mark.parametrize("how", ["record_batches", "parquet"])
@pytest.mark.parametrize("tol", [0.0, 1e-4], ids=["tol0", "default-tol"])
@pytest.mark.parametrize("seed", [0, 1, 2])
def test_kmeans_fit_matches_sklearn(ctx, tmp_path, seed, tol, how):
    X, init = blobs(seed)
    expected = pipeline(init, tol=tol).fit(X)
    # Empty clusters are a documented limitation: sklearn relocates them.
    assert np.bincount(expected[1].labels_, minlength=len(init)).min() > 0

    fitted = ml.fit(pipeline(init, tol=tol), register(ctx, how, X, tmp_path))

    assert fitted[1].n_iter_ == expected[1].n_iter_
    np.testing.assert_allclose(
        fitted[1].cluster_centers_, expected[1].cluster_centers_, rtol=RTOL, atol=ATOL
    )
    np.testing.assert_allclose(fitted[1].inertia_, expected[1].inertia_, rtol=RTOL)
    for attr in ("mean_", "var_", "scale_"):
        np.testing.assert_allclose(
            getattr(fitted[0], attr), getattr(expected[0], attr), rtol=RTOL, atol=ATOL
        )
    np.testing.assert_array_equal(fitted.predict(X), expected.predict(X))


def test_kmeans_fit_stops_at_max_iter(ctx, tmp_path):
    X, init = blobs(3)
    expected = pipeline(init, tol=0.0, max_iter=2).fit(X)
    fitted = ml.fit(
        pipeline(init, tol=0.0, max_iter=2),
        register(ctx, "record_batches", X, tmp_path),
    )
    assert fitted[1].n_iter_ == expected[1].n_iter_ == 2
    np.testing.assert_allclose(
        fitted[1].cluster_centers_, expected[1].cluster_centers_, rtol=RTOL, atol=ATOL
    )
    np.testing.assert_allclose(fitted[1].inertia_, expected[1].inertia_, rtol=RTOL)


def test_kmeans_fit_on_a_single_shot_reader(ctx):
    # The loop re-reads its input every iteration; a reader can be read once.
    X, init = blobs(4)
    table = pa.table({f"x{j}": X[:, j] for j in range(3)})
    ctx.register_record_batch_reader(
        "t", pa.RecordBatchReader.from_batches(table.schema, table.to_batches())
    )
    fitted = ml.fit(pipeline(init), ctx.table("t"))
    expected = pipeline(init).fit(X)
    assert fitted[1].n_iter_ == expected[1].n_iter_
    np.testing.assert_allclose(
        fitted[1].cluster_centers_, expected[1].cluster_centers_, rtol=RTOL, atol=ATOL
    )


@pytest.mark.parametrize("tol", [0.0, 1e-4], ids=["tol0", "default-tol"])
@pytest.mark.parametrize(
    ("values", "match"),
    [
        ([0.0, None, 2.0], "missing values"),
        ([0.0, float("nan"), 2.0], "NaN or infinite"),
    ],
    ids=["null", "nan"],
)
def test_kmeans_only_fit_validates_its_input(ctx, tol, values, match):
    ctx.register_record_batches(
        "t", [[pa.record_batch({"x": pa.array(values, pa.float64())})]]
    )
    request = {
        "features": ["x"],
        "steps": [
            {
                "kind": "kmeans",
                "n_clusters": 1,
                "init": [[0.0]],
                "max_iter": 10,
                "tol": tol,
            }
        ],
    }
    with pytest.raises(ValueError, match=match):
        _native.fit(ctx.table("t"), json.dumps(request))
