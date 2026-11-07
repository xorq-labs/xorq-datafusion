"""
Fit and predict a scikit-learn pipeline inside DataFusion.

    uv run python examples/ml_demo.py

Generates four blobs, writes them to Parquet, registers the file, fits
``StandardScaler -> KMeans`` natively, labels the rows natively, queries the
labels with SQL, and checks everything against scikit-learn.
"""

import tempfile
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from sklearn.cluster import KMeans
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

import xorq_datafusion.ml as ml
from xorq_datafusion import SessionConfig, SessionContext

FEATURES = ["x0", "x1", "x2"]


def make_blobs(seed=0, per_blob=2_500):
    """
    Make four well-separated blobs, shuffled, and one initial center per blob.

    Returns:
        The rows and the initial centers (in scaled space, which KMeans sees).

    """
    rng = np.random.default_rng(seed)
    centers = np.array([[0, 0, 0], [8, 8, 0], [0, 8, 8], [8, 0, 8]], dtype=float)
    X = np.vstack([c + rng.normal(size=(per_blob, 3)) for c in centers])
    X = X[rng.permutation(len(X))]
    # KMeans sees scaled data, so its initial centers live in scaled space.
    init = StandardScaler().fit_transform(X)[:4]
    return X, init


def pipeline(init):
    """
    Build the demo pipeline, unfitted.

    Returns:
        ``StandardScaler -> KMeans(4)`` starting from ``init``.

    """
    return make_pipeline(StandardScaler(), KMeans(4, init=init, n_init=1))


def main():
    """Fit, predict, query and compare; raise if anything differs from sklearn."""
    X, init = make_blobs()
    ctx = SessionContext(config=SessionConfig().with_target_partitions(4))

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "blobs.parquet"
        table = pa.table(
            {f: X[:, j] for j, f in enumerate(FEATURES)} | {"id": np.arange(len(X))}
        )
        pq.write_table(table, path, row_group_size=2_500)
        ctx.register_parquet("blobs", [str(path)])
        df = ctx.sql("SELECT id, x0, x1, x2 FROM blobs")

        # 1. fit natively: Python only builds a spec and writes attributes back
        fitted = ml.fit(pipeline(init), df, features=FEATURES)
        scaler, kmeans = fitted[0], fitted[1]
        print("StandardScaler.mean_ ", np.round(scaler.mean_, 4))
        print("StandardScaler.scale_", np.round(scaler.scale_, 4))
        print("KMeans.n_iter_       ", kmeans.n_iter_)
        print("KMeans.inertia_      ", round(kmeans.inertia_, 4))

        # 2. predict natively: the result is an ordinary DataFrame
        model = ml.compile(fitted, FEATURES)
        ctx.register_dataframe("labelled", model.predict(df))
        counts = ctx.sql(
            "SELECT label, count(*) AS n FROM labelled GROUP BY label ORDER BY label"
        )
        print(
            "rows per label       ",
            dict(zip(*counts.to_arrow_table().to_pydict().values(), strict=False)),
        )
        threes = ctx.sql("SELECT id FROM labelled WHERE label = 3").to_arrow_table()
        print("rows with label 3    ", threes.num_rows)

        print("\noptimized predict plan:")
        print(model.explain("optimized"))

        # 3. the same pipeline fitted by scikit-learn
        expected = pipeline(init).fit(X)
        np.testing.assert_allclose(
            kmeans.cluster_centers_, expected[1].cluster_centers_, rtol=1e-7, atol=1e-9
        )
        np.testing.assert_allclose(kmeans.inertia_, expected[1].inertia_, rtol=1e-7)
        assert kmeans.n_iter_ == expected[1].n_iter_
        labelled = ctx.sql(
            "SELECT id, label FROM labelled ORDER BY id"
        ).to_arrow_table()
        assert labelled.column("label").to_pylist() == expected.predict(X).tolist()
        assert threes.num_rows == int((expected.predict(X) == 3).sum())
        print(
            "\nmatches scikit-learn: cluster_centers_, inertia_, n_iter_, every label"
        )


if __name__ == "__main__":
    main()
