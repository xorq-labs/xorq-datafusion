"""
Public entry points of the ML layer.

Python never touches row data here: these functions inspect scikit-learn
objects and a DataFrame's schema, exchange JSON specs with the native layer
(``xorq_datafusion._internal.ml``), and write fitted attributes back.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from xorq_datafusion._internal import ml as _native
from xorq_datafusion.ml.frontend import (
    Reason,
    Supported,
    Unsupported,
    apply_fit_result,
    check,
    default_features,
    to_fit_spec,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from xorq_datafusion import DataFrame

__all__ = [
    "Model",
    "Reason",
    "Supported",
    "Unsupported",
    "compile",
    "fit",
    "supports",
]

STAGES = ("logical", "optimized", "physical", "parallel")


def supports(estimator) -> Supported | Unsupported:
    """
    Report whether ``estimator`` can be fitted and compiled natively.

    Supported today: ``Pipeline[StandardScaler, KMeans]`` whose KMeans has an
    array ``init``, ``n_init=1`` (or ``"auto"``) and ``algorithm="lloyd"``.

    Returns:
        :class:`Supported`, or :class:`Unsupported` with a :class:`Reason`.

    """
    return check(estimator)


def fit(pipeline, df: DataFrame, features: Sequence[str] | None = None):
    """
    Fit ``pipeline`` on ``df`` inside DataFusion, in place.

    ``df`` is any :class:`~xorq_datafusion.DataFrame` (``ctx.sql``,
    ``ctx.table``, ...); the fit plans are built on its logical plan and run
    with its session. ``features`` default to the numeric columns of
    ``df.schema()``, in order. Ctrl-C cancels the fit.

    Returns:
        The same pipeline object, with scikit-learn's fitted attributes set,
        so its own ``predict``/``transform`` work.

    """
    if features is None:
        features = default_features(df.schema())
    spec = to_fit_spec(pipeline, features)
    result = json.loads(_native.fit(df, json.dumps(spec)))
    apply_fit_result(pipeline, result)
    return pipeline


def compile(fitted, features: Sequence[str] | None = None) -> Model:
    """
    Compile a fitted pipeline into a :class:`Model` that predicts natively.

    Raises:
        NotImplementedError: not implemented yet.

    """
    raise NotImplementedError("xorq_datafusion.ml.compile")


class Model:
    """A compiled pipeline: predicts inside DataFusion."""

    def predict(self, df: DataFrame) -> DataFrame:
        """
        Return ``df`` with a ``label`` column added.

        The result is an ordinary :class:`~xorq_datafusion.DataFrame`.

        Raises:
            NotImplementedError: not implemented yet.

        """
        raise NotImplementedError("Model.predict")

    def explain(self, stage: str = "optimized") -> str:
        """
        Render the predict plan at ``stage``.

        ``stage`` is one of ``logical``, ``optimized``, ``physical`` or
        ``parallel`` (reserved). The plan is built over an empty input with
        the model's feature columns, so the output is deterministic.

        Raises:
            NotImplementedError: not implemented yet.

        """
        raise NotImplementedError("Model.explain")
