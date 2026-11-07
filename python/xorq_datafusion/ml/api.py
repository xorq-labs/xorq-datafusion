"""
Public entry points of the ML layer.

Python never touches row data here: these functions inspect scikit-learn
objects and a DataFrame's schema, exchange JSON specs with the native layer
(``xorq_datafusion._internal.ml``), and write fitted attributes back.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from xorq_datafusion import DataFrame

STAGES = ("logical", "optimized", "physical", "parallel")


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


def supports(estimator) -> Supported | Unsupported:
    """
    Report whether ``estimator`` can be fitted and compiled natively.

    Raises:
        NotImplementedError: not implemented yet.

    """
    raise NotImplementedError("xorq_datafusion.ml.supports")


def fit(pipeline, df: DataFrame, features: Sequence[str] | None = None):
    """
    Fit ``pipeline`` on ``df`` inside DataFusion, in place.

    ``features`` default to the numeric columns of ``df.schema()``, in order.
    Returns the same pipeline object, with scikit-learn's fitted attributes
    set, so its own ``predict``/``transform`` work.

    Raises:
        NotImplementedError: not implemented yet.

    """
    raise NotImplementedError("xorq_datafusion.ml.fit")


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
