"""
Translate between scikit-learn objects and the native pipeline spec v0.

Only scikit-learn objects and schemas are inspected here; row data never
passes through Python. Specs are plain dicts, serialized to JSON at the
boundary with ``xorq_datafusion._internal.ml``.
"""

from __future__ import annotations

import enum
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
import pyarrow as pa
from sklearn.cluster import KMeans
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.utils._openmp_helpers import _openmp_effective_n_threads
from sklearn.utils.validation import check_is_fitted

from xorq_datafusion._internal import ml as _native

if TYPE_CHECKING:
    from collections.abc import Sequence


class Reason(str, enum.Enum):
    """Why an estimator is not supported by the native ML layer."""

    UNSUPPORTED_ESTIMATOR = "unsupported estimator"
    UNSUPPORTED_PARAMETER = "unsupported parameter"
    UNSUPPORTED_PIPELINE_SHAPE = "unsupported pipeline shape"
    NEEDS_FINE_GRAINED_MUTATION = "needs fine-grained mutation"


@dataclass(frozen=True)
class Supported:
    """The estimator can be fitted and compiled natively."""

    def __bool__(self) -> bool:
        """
        Make the result usable in a boolean context.

        Returns:
            Always ``True``.

        """
        return True


@dataclass(frozen=True)
class Unsupported:
    """The estimator cannot be handled natively, and why."""

    reason: Reason
    detail: str = ""

    def __bool__(self) -> bool:
        """
        Make the result usable in a boolean context.

        Returns:
            Always ``False``.

        """
        return False


class UnsupportedError(ValueError):
    """The estimator cannot be handled natively; carries the :class:`Unsupported`."""

    def __init__(self, unsupported: Unsupported):
        """Wrap ``unsupported``; the message is its reason and detail."""
        self.unsupported = unsupported
        detail = f": {unsupported.detail}" if unsupported.detail else ""
        super().__init__(f"{unsupported.reason.value}{detail}")


def check(estimator) -> Supported | Unsupported:
    """
    Classify ``estimator``; see :func:`xorq_datafusion.ml.supports`.

    Returns:
        :class:`Supported`, or :class:`Unsupported` with the first reason found.

    """
    if not isinstance(estimator, Pipeline):
        return Unsupported(
            Reason.UNSUPPORTED_ESTIMATOR,
            f"expected a Pipeline, got {type(estimator).__name__}",
        )
    steps = [step for _, step in estimator.steps]
    kinds = [type(step) for step in steps]
    if kinds != [StandardScaler, KMeans]:
        names = ", ".join(kind.__name__ for kind in kinds)
        return Unsupported(
            Reason.UNSUPPORTED_PIPELINE_SHAPE,
            f"expected Pipeline[StandardScaler, KMeans], got [{names}]",
        )
    return _check_kmeans(steps[1])


def _check_kmeans(kmeans: KMeans) -> Supported | Unsupported:
    if isinstance(kmeans.init, str) or callable(kmeans.init):
        return Unsupported(
            Reason.UNSUPPORTED_PARAMETER, "KMeans.init must be an array of centroids"
        )
    init = np.asarray(kmeans.init, dtype=np.float64)
    if init.ndim != 2 or init.shape[0] != kmeans.n_clusters:
        return Unsupported(
            Reason.UNSUPPORTED_PARAMETER,
            f"KMeans.init must have shape (n_clusters={kmeans.n_clusters}, "
            f"n_features), got {init.shape}",
        )
    if kmeans.n_init not in (1, "auto"):
        return Unsupported(Reason.UNSUPPORTED_PARAMETER, "KMeans.n_init must be 1")
    if kmeans.algorithm != "lloyd":
        return Unsupported(
            Reason.UNSUPPORTED_PARAMETER, 'KMeans.algorithm must be "lloyd"'
        )
    return Supported()


def _require_supported(pipeline) -> tuple[StandardScaler, KMeans]:
    verdict = check(pipeline)
    if not verdict:
        raise UnsupportedError(verdict)
    scaler, kmeans = (step for _, step in pipeline.steps)
    return scaler, kmeans


def _check_features(features: Sequence[str], n_features: int | None = None) -> list:
    features = list(features)
    if n_features is not None and len(features) != n_features:
        raise ValueError(
            f"features: expected {n_features} columns, got {len(features)}"
        )
    return features


def default_features(schema: pa.Schema) -> list[str]:
    """
    Return the numeric (integer or floating) columns of ``schema``, in order.

    Returns:
        The column names.

    """
    return [
        field.name
        for field in schema
        if pa.types.is_integer(field.type) or pa.types.is_floating(field.type)
    ]


def to_fit_spec(pipeline, features: Sequence[str]) -> dict:
    """
    Build the fit request for an unfitted supported ``pipeline``.

    Returns:
        The fit request, validated by the native layer.

    """
    scaler, kmeans = _require_supported(pipeline)
    init = np.asarray(kmeans.init, dtype=np.float64)
    spec = {
        "features": _check_features(features, init.shape[1]),
        "steps": [
            {
                "kind": "standard_scaler",
                "with_mean": bool(scaler.with_mean),
                "with_std": bool(scaler.with_std),
            },
            {
                "kind": "kmeans",
                "n_clusters": int(kmeans.n_clusters),
                "init": init.tolist(),
                "max_iter": int(kmeans.max_iter),
                "tol": float(kmeans.tol),
            },
        ],
    }
    return json.loads(_native.validate_fit_request(json.dumps(spec)))


def _optional_list(value) -> list | None:
    return None if value is None else np.asarray(value, dtype=np.float64).tolist()


def to_compile_spec(fitted, features: Sequence[str]) -> dict:
    """
    Build the compile request for a fitted supported pipeline.

    Returns:
        The compile request, validated by the native layer.

    """
    scaler, kmeans = _require_supported(fitted)
    check_is_fitted(scaler)
    check_is_fitted(kmeans)
    spec = {
        "features": _check_features(features, scaler.n_features_in_),
        "steps": [
            {
                "kind": "standard_scaler",
                "with_mean": bool(scaler.with_mean),
                "with_std": bool(scaler.with_std),
                "mean": _optional_list(scaler.mean_),
                "var": _optional_list(scaler.var_),
                "scale": _optional_list(scaler.scale_),
                "n_samples_seen": int(scaler.n_samples_seen_),
            },
            {
                "kind": "kmeans",
                "cluster_centers": np.asarray(
                    kmeans.cluster_centers_, dtype=np.float64
                ).tolist(),
                "inertia": float(kmeans.inertia_),
                "n_iter": int(kmeans.n_iter_),
            },
        ],
    }
    return json.loads(_native.validate_compile_request(json.dumps(spec)))


def _optional_array(value) -> np.ndarray | None:
    return None if value is None else np.asarray(value, dtype=np.float64)


def apply_fit_result(pipeline, result: dict) -> None:
    """
    Set scikit-learn's fitted attributes on ``pipeline`` from a fit result.

    Sets exactly what scikit-learn 1.7's own ``fit`` sets and its
    ``transform``/``predict`` read, so the pipeline's own methods work.
    ``KMeans.labels_`` (training labels) is not set: the native fit does not
    return per-row results.

    Raises:
        ValueError: ``result`` does not match ``pipeline``.

    """
    scaler, kmeans = _require_supported(pipeline)
    n_features = np.asarray(kmeans.init).shape[1]
    result = json.loads(_native.validate_fit_result(json.dumps(result), n_features))
    fitted_scaler, fitted_kmeans = result["steps"]
    if fitted_scaler["kind"] != "standard_scaler" or fitted_kmeans["kind"] != "kmeans":
        raise ValueError("fit result: steps must be [standard_scaler, kmeans]")
    flags = (fitted_scaler["with_mean"], fitted_scaler["with_std"])
    if flags != (bool(scaler.with_mean), bool(scaler.with_std)):
        raise ValueError("fit result: with_mean/with_std do not match the pipeline")
    centers = np.asarray(fitted_kmeans["cluster_centers"], dtype=np.float64)
    if centers.shape[0] != kmeans.n_clusters:
        raise ValueError(
            f"fit result: expected {kmeans.n_clusters} cluster centers, "
            f"got {centers.shape[0]}"
        )

    scaler.mean_ = _optional_array(fitted_scaler["mean"])
    scaler.var_ = _optional_array(fitted_scaler["var"])
    scaler.scale_ = _optional_array(fitted_scaler["scale"])
    scaler.n_samples_seen_ = int(fitted_scaler["n_samples_seen"])
    scaler.n_features_in_ = n_features

    kmeans.cluster_centers_ = centers
    kmeans.inertia_ = float(fitted_kmeans["inertia"])
    kmeans.n_iter_ = int(fitted_kmeans["n_iter"])
    kmeans.n_features_in_ = n_features
    kmeans._n_features_out = centers.shape[0]
    kmeans._n_threads = _openmp_effective_n_threads()
