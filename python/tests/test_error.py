from __future__ import annotations

from operator import methodcaller

import pyarrow as pa
import pyarrow.compute as pc
import pytest

from xorq_datafusion import Accumulator, udaf


class ErrorSummarize(Accumulator):
    """Interface of a user-defined accumulation."""

    def __init__(self, initial_value: float = 0.0):
        self._sum = pa.scalar(initial_value)

    def state(self) -> list[pa.Scalar]:
        return [self._sum]

    def update(self, values: pa.Array) -> None:
        # Not nice since pyarrow scalars can't be summed yet.
        # This breaks on `None`
        self._sum = pa.scalar(self._sum.as_py() + pc.sum(values).as_py())

    def merge(self, states: list[pa.Array]) -> None:
        # Not nice since pyarrow scalars can't be summed yet.
        # This breaks on `None`
        self._sum = pa.scalar(self._sum.as_py() + pc.sum(states[0]).as_py())

    def evaluate(self) -> pa.Scalar:
        raise Exception


@pytest.fixture(scope="function")
def ctx_with_table(ctx):
    # create a RecordBatch and a new DataFrame from it
    batch = pa.RecordBatch.from_arrays(
        [pa.array([1, 2, 3]), pa.array([4, 4, 6])],
        names=["a", "b"],
    )
    ctx.register_record_batches("test_table", [[batch]])
    return ctx


def has_stacktrace(e, pattern=None):
    import re
    import traceback
    import io

    buffer = io.StringIO()
    traceback.print_exception(e, file=buffer)

    if pattern:
        return re.search(pattern, buffer.getvalue()) is not None
    return buffer.getvalue()


@pytest.mark.parametrize(
    "execute_method", [methodcaller("collect"), lambda f: next(f.execute_stream())]
)
def test_udaf_aggregate(ctx_with_table, execute_method):
    summarize = udaf(
        ErrorSummarize,
        [pa.float64()],
        pa.float64(),
        [pa.float64()],
        volatility="immutable",
        name="error_summarize",
    )

    ctx_with_table.register_udaf(summarize)

    df1 = ctx_with_table.sql("select error_summarize(a) from test_table")

    with pytest.raises(Exception) as error:
        execute_method(df1)

    assert has_stacktrace(error.value, pattern=r"in\s+evaluate")
