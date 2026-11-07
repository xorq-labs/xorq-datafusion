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
    to_compile_spec,
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

    ``fitted`` may come from :func:`fit` or from scikit-learn's own ``fit``.
    ``features`` name the input columns, in the order the pipeline was
    fitted on; when omitted they are the pipeline's ``feature_names_in_``
    if it has them, else the numeric columns of each DataFrame passed to
    :meth:`Model.predict`.

    Returns:
        The compiled :class:`Model`.

    """
    if features is None:
        names = getattr(fitted.steps[0][1], "feature_names_in_", None)
        features = None if names is None else [str(name) for name in names]
    n_features = (
        fitted.steps[0][1].n_features_in_
        if hasattr(fitted.steps[0][1], "n_features_in_")
        else None
    )
    placeholder = features or [f"x{j}" for j in range(n_features or 0)]
    spec = to_compile_spec(fitted, placeholder)
    return Model(spec["steps"], None if features is None else list(features))


class Model:
    """A compiled pipeline: predicts inside DataFusion."""

    def __init__(self, steps: list[dict], features: list[str] | None):
        """Hold fitted ``steps`` (spec v0) and the input ``features``, if known."""
        self._steps = steps
        self._features = features

    @property
    def features(self) -> list[str] | None:
        """The input columns, or ``None`` when taken from each DataFrame."""
        return self._features

    def _request(self, features: Sequence[str]) -> str:
        return json.dumps({"features": list(features), "steps": self._steps})

    def _n_features(self) -> int:
        return len(self._steps[0].get("mean") or self._steps[-1]["cluster_centers"][0])

    def predict(self, df: DataFrame) -> DataFrame:
        """
        Return ``df`` with an Int64 ``label`` column added.

        The labels are computed natively when the result executes. The result
        is an ordinary :class:`~xorq_datafusion.DataFrame`: filter it, join
        it, register it, collect it.

        Returns:
            The labelled DataFrame.

        Raises:
            ValueError: the model's features do not match ``df``.

        """
        features = self._features or default_features(df.schema())
        if len(features) != self._n_features():
            raise ValueError(
                f"model expects {self._n_features()} features, got {len(features)}: "
                f"{features}"
            )
        return _native.predict(df, self._request(features), "label")

    def explain(self, stage: str = "optimized") -> str:
        """
        Render the predict plan at ``stage``.

        ``stage`` is one of ``logical``, ``optimized``, ``physical`` or
        ``parallel`` (reserved: returns ``"not yet implemented"``). The plan
        is built over an empty input with the model's feature columns, so the
        output is deterministic.

        Returns:
            The rendered plan.

        Raises:
            ValueError: unknown ``stage``.

        """
        if stage == "parallel":
            return "not yet implemented"
        if stage not in ("logical", "optimized", "physical"):
            raise ValueError(f"stage must be one of {STAGES}, got {stage!r}")
        features = self._features or [f"x{j}" for j in range(self._n_features())]
        return _native.explain_predict(self._request(features), "label", stage)
