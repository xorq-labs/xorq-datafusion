"""Explain output of ML plans, compared verbatim with python/tests/ml/golden.

Regenerate with ``UPDATE_GOLDEN=1 pytest python/tests/ml/test_golden.py``.
"""

import json
import os
from pathlib import Path

import numpy as np
import pyarrow as pa
import pytest
from sklearn.cluster import KMeans
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from xorq_datafusion._internal import ml as _native
from xorq_datafusion.ml.frontend import to_fit_spec

GOLDEN = Path(__file__).with_name("golden")
UPDATE = os.environ.get("UPDATE_GOLDEN") == "1"


def check(name, actual):
    path = GOLDEN / f"{name}.txt"
    if UPDATE:
        path.write_text(actual + "\n")
    assert actual + "\n" == path.read_text(), (
        f"{name} differs; UPDATE_GOLDEN=1 regenerates"
    )


@pytest.fixture
def fit_request(ctx):
    X = np.array([[-1.0, 1.0], [1.0, 1.0], [-1.0, -1.0], [1.0, -1.0]])
    ctx.register_record_batches(
        "t", [pa.table({"a": X[:, 0], "b": X[:, 1]}).to_batches()]
    )
    init = np.array([[-1.0, 0.0], [1.0, 0.0]])
    pipeline = make_pipeline(StandardScaler(), KMeans(2, init=init, n_init=1, tol=0.0))
    return ctx.table("t"), json.dumps(to_fit_spec(pipeline, ["a", "b"]))


@pytest.mark.parametrize("stage", ["logical", "optimized"])
def test_fit_plan(fit_request, stage):
    df, request = fit_request
    check(f"fit_{stage}", _native.explain_fit(df, request, stage))
