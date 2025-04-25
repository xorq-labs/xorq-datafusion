from __future__ import annotations

import pyarrow as pa
import pyarrow.compute as pc
import pytest

from xorq_datafusion import Accumulator, udaf


class Summarize(Accumulator):
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
        return self._sum


@pytest.fixture(scope="function")
def ctx_with_table(ctx):
    # create a RecordBatch and a new DataFrame from it
    batch = pa.RecordBatch.from_arrays(
        [pa.array([1, 2, 3]), pa.array([4, 4, 6])],
        names=["a", "b"],
    )
    ctx.register_record_batches("test_table", [[batch]])
    return ctx


def test_udaf_aggregate(ctx_with_table):
    summarize = udaf(
        Summarize,
        [pa.float64()],
        pa.float64(),
        [pa.float64()],
        volatility="immutable",
    )

    ctx_with_table.register_udaf(summarize)

    df1 = ctx_with_table.sql("select summarize(a) from test_table")

    # execute and collect the first (and only) batch
    result = df1.collect()[0]

    assert result.column(0) == pa.array([1.0 + 2.0 + 3.0])

    df2 = ctx_with_table.sql("select summarize(a) from test_table")

    # Run a second time to ensure the state is properly reset
    result = df2.collect()[0]

    assert result.column(0) == pa.array([1.0 + 2.0 + 3.0])


def test_group_by(ctx_with_table):
    summarize = udaf(
        Summarize,
        [pa.float64()],
        pa.float64(),
        [pa.float64()],
        volatility="immutable",
    )

    ctx_with_table.register_udaf(summarize)

    batches = ctx_with_table.sql(
        "select b, summarize(a) from test_table group by b"
    ).collect()

    arrays = [batch.column(1) for batch in batches]
    joined = pa.concat_arrays(arrays)
    assert joined == pa.array([1.0 + 2.0, 3.0])


def test_register_udaf(ctx_with_table) -> None:
    summarize = udaf(
        Summarize,
        [pa.float64()],
        pa.float64(),
        [pa.float64()],
        volatility="immutable",
    )

    ctx_with_table.register_udaf(summarize)

    df_result = ctx_with_table.sql("select summarize(b) from test_table")

    assert df_result.collect()[0][0][0].as_py() == 14.0
