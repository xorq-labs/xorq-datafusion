"""
Python bindings for the xorq DataFusion engine.

Exposes the session/context API together with the abstract base classes used
to register user-defined scalar, aggregate and window functions.
"""

import atexit
from abc import ABCMeta, abstractmethod

import pyarrow as pa

from xorq_datafusion._internal import (
    AggregateUDF,
    ContextProvider,
    DataFrame,
    LogicalPlan,
    LogicalPlanBuilder,
    OptimizerContext,
    OptimizerRule,
    ScalarUDF,
    SessionConfig,
    SessionContext,
    SessionState,
    Table,
    TableProvider,
    WindowUDF,
)
from xorq_datafusion._internal import (
    runtime as _runtime,
)

try:
    import importlib.metadata as importlib_metadata
except ModuleNotFoundError:
    import importlib_metadata


def close(timeout_secs=None):
    """Shut down the background runtime, waiting up to ``timeout_secs``."""
    _runtime.shutdown(timeout_secs)


atexit.register(close)

__all__ = [
    "AbstractTableProvider",
    "Accumulator",
    "AggregateUDF",
    "ContextProvider",
    "DataFrame",
    "LogicalPlan",
    "LogicalPlanBuilder",
    "OptimizationRule",
    "OptimizerContext",
    "OptimizerRule",
    "ScalarUDF",
    "SessionConfig",
    "SessionContext",
    "SessionState",
    "Table",
    "TableProvider",
    "WindowEvaluator",
    "WindowUDF",
    "close",
]


class Accumulator(metaclass=ABCMeta):
    """Aggregation state for a user-defined aggregate function."""

    @abstractmethod
    def state(self) -> list[pa.Scalar]:
        """Return the current intermediate state."""

    @abstractmethod
    def update(self, values: pa.Array) -> None:
        """Update the state with a batch of input values."""

    @abstractmethod
    def merge(self, states: pa.Array) -> None:
        """Merge intermediate states produced by other accumulators."""

    @abstractmethod
    def evaluate(self) -> pa.Scalar:
        """Return the final aggregate value."""


class OptimizationRule(metaclass=ABCMeta):
    """A user-defined logical-plan optimization rule."""

    @abstractmethod
    def try_optimize(self, plan: LogicalPlan) -> LogicalPlan:
        """Return an optimized plan, or the input plan if unchanged."""


class AbstractTableProvider(metaclass=ABCMeta):
    """A user-defined source that exposes a schema and scannable data."""

    @abstractmethod
    def schema(self):
        """Return the schema of the table."""

    @abstractmethod
    def scan(self, filters=None):
        """Return the table data, optionally pushing down ``filters``."""


class WindowEvaluator(metaclass=ABCMeta):  # noqa: B024
    """
    Base class for user-defined window functions.

    Subclasses override the subset of methods their window function needs;
    the defaults below describe a simple, unbounded, non-ranking evaluator.
    No method is marked ``@abstractmethod`` because each one is optional to
    override.
    """

    def memoize(self) -> None:  # noqa: B027
        """Cache state between calls; no-op by default."""

    def get_range(self, idx: int, num_rows: int) -> tuple[int, int]:
        """
        Return the row range to evaluate for ``idx``.

        Returns:
            The ``[start, end)`` row range.

        """
        return idx, idx + 1

    def is_causal(self) -> bool:
        """
        Report whether the function only depends on preceding rows.

        Returns:
            ``True`` if evaluation is causal.

        """
        return False

    def evaluate_all(self, values: list[pa.Array], num_rows: int) -> pa.Array:  # noqa: B027
        """Evaluate the function over every row of the partition."""

    def evaluate(  # noqa: B027
        self, values: list[pa.Array], eval_range: tuple[int, int]
    ) -> pa.Scalar:
        """Evaluate the function for a single row over ``eval_range``."""

    def evaluate_all_with_rank(  # noqa: B027
        self, num_rows: int, ranks_in_partition: list[tuple[int, int]]
    ) -> pa.Array:
        """Evaluate using only the rank ranges of the partition."""

    def supports_bounded_execution(self) -> bool:
        """
        Report whether the function supports bounded (streaming) eval.

        Returns:
            ``True`` if bounded execution is supported.

        """
        return False

    def uses_window_frame(self) -> bool:
        """
        Report whether the function reads the window frame.

        Returns:
            ``True`` if the window frame is used.

        """
        return False

    def include_rank(self) -> bool:
        """
        Report whether the function needs partition rank information.

        Returns:
            ``True`` if rank information is required.

        """
        return False


def udf(func, input_types, return_type, volatility, name=None):
    """
    Create a new User Defined Function.

    Returns:
        A scalar user-defined function.

    Raises:
        TypeError: If ``func`` is not callable.

    """
    if not callable(func):
        raise TypeError("`func` argument must be callable")
    if name is None:
        name = func.__qualname__.lower()
    return ScalarUDF(
        name=name,
        func=func,
        input_types=input_types,
        return_type=return_type,
        volatility=volatility,
    )


def udaf(accum, input_type, return_type, state_type, volatility, name=None):
    """
    Create a new User Defined Aggregate Function.

    Returns:
        An aggregate user-defined function.

    Raises:
        TypeError: If ``accum`` does not implement ``Accumulator``.

    """
    if not issubclass(accum, Accumulator):
        raise TypeError("`accum` must implement the abstract base class Accumulator")
    if name is None:
        name = accum.__qualname__.lower()
    return AggregateUDF(
        name=name,
        accumulator=accum,
        input_type=input_type,
        return_type=return_type,
        state_type=state_type,
        volatility=volatility,
    )


def udwf(
    func: WindowEvaluator,
    input_types: pa.DataType | list[pa.DataType],
    return_type: pa.DataType,
    volatility: str,
    name: str | None = None,
) -> WindowUDF:
    """
    Create a new User-Defined Window Function.

    Args:
        func: The python function.
        input_types: The data types of the arguments to ``func``.
        return_type: The data type of the return value.
        volatility: See :py:class:`Volatility` for allowed values.
        name: A descriptive name for the function.

    Returns:
        A user-defined window function.

    Raises:
        TypeError: If ``func`` does not implement ``WindowEvaluator``.

    """
    if not isinstance(func, WindowEvaluator):
        raise TypeError("`func` must implement the abstract base class WindowEvaluator")
    if name is None:
        name = func.__class__.__qualname__.lower()
    if isinstance(input_types, pa.DataType):
        input_types = [input_types]

    return WindowUDF(name, func, input_types, return_type, str(volatility))


__version__ = importlib_metadata.version(__package__)
