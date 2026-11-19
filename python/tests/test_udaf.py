from __future__ import annotations

import pyarrow as pa
import pyarrow.compute as pc
import pytest

from xorq_datafusion import Accumulator, SessionConfig, SessionContext, udaf


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

    def merge(self, states: pa.Array) -> None:
        # One array holding every partial state for this group.
        # Not nice since pyarrow scalars can't be summed yet.
        # This breaks on `None`
        self._sum = pa.scalar(self._sum.as_py() + pc.sum(states).as_py())

    def evaluate(self) -> pa.Scalar:
        return self._sum


@pytest.fixture
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


def test_group_by_merges_every_partial_state():
    """merge() gets one array with a partial state per input partition."""
    ctx = SessionContext(
        config=SessionConfig().with_target_partitions(4).with_batch_size(64)
    )
    xs = list(range(1_000))
    batches = [
        pa.RecordBatch.from_arrays(
            [pa.array(xs[s : s + 50]), pa.array([x % 3 for x in xs[s : s + 50]])],
            names=["a", "b"],
        )
        for s in range(0, len(xs), 50)
    ]
    ctx.register_record_batches("t", [batches])
    ctx.register_udaf(
        udaf(
            Summarize,
            [pa.float64()],
            pa.float64(),
            [pa.float64()],
            volatility="immutable",
        )
    )

    result = ctx.sql("select b, summarize(a) as s from t group by b order by b")
    got = {
        b: s
        for rb in result.collect()
        for b, s in zip(rb.column(0).to_pylist(), rb.column(1).to_pylist(), strict=True)
    }
    assert got == {k: float(sum(x for x in xs if x % 3 == k)) for k in range(3)}
