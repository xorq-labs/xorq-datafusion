"""A Python callback that returns the wrong kind of value raises an error.

These conversions used to ``unwrap()``, so a bad return value panicked the
thread running the callback (often a tokio worker) instead of failing the query.
"""

import pyarrow as pa
import pytest

from xorq_datafusion import SessionContext, SessionState, WindowEvaluator, udf, udwf


def _assert_plain_error(excinfo):
    # pyo3 surfaces a Rust panic as PanicException, which derives from
    # BaseException, so pytest.raises(Exception) already rejects it; this
    # guards against a panic message re-raised as an ordinary exception.
    assert "panicked" not in str(excinfo.value)


@pytest.fixture
def ctx_table(ctx):
    batch = pa.RecordBatch.from_arrays(
        [pa.array([1, 2, 3]), pa.array([4, 5, 6])], names=["a", "b"]
    )
    ctx.register_record_batches("t", [[batch]])
    return ctx


def test_scalar_udf_returning_non_array_raises(ctx_table):
    not_an_array = udf(
        lambda x: 42,
        [pa.int64()],
        pa.int64(),
        volatility="immutable",
        name="not_an_array",
    )
    ctx_table.register_udf(not_an_array)

    with pytest.raises(
        Exception, match="Expected instance of pyarrow.lib.Array"
    ) as excinfo:
        ctx_table.sql("select not_an_array(a) from t").collect()
    _assert_plain_error(excinfo)


def test_scalar_udf_returning_wrong_type_raises(ctx_table):
    wrong_type = udf(
        lambda x: pa.array([0.5] * len(x)),
        [pa.int64()],
        pa.int64(),
        volatility="immutable",
        name="wrong_type",
    )
    ctx_table.register_udf(wrong_type)

    # sum downcasts its input to the declared type and panicked on a mismatch.
    with pytest.raises(Exception, match="expected Int64") as excinfo:
        ctx_table.sql("select sum(wrong_type(a)) from t").collect()
    _assert_plain_error(excinfo)


def test_scalar_udf_returning_empty_array_for_scalar_args_raises(ctx_table):
    empty = udf(
        lambda x: pa.array([], pa.int64()),
        [pa.int64()],
        pa.int64(),
        volatility="immutable",
        name="empty",
    )
    ctx_table.register_udf(empty)

    with pytest.raises(Exception, match="empty array") as excinfo:
        ctx_table.sql("select empty(1)").collect()
    _assert_plain_error(excinfo)


class _NotAnArrayEvaluator(WindowEvaluator):
    def evaluate_all(self, values, num_rows):
        return [0.0] * num_rows


def test_udwf_evaluate_all_returning_non_array_raises(ctx_table):
    not_an_array = udwf(
        _NotAnArrayEvaluator(),
        [pa.int64()],
        pa.float64(),
        volatility="immutable",
        name="not_an_array_window",
    )
    ctx_table.register_udwf(not_an_array)

    with pytest.raises(
        Exception, match="Expected instance of pyarrow.lib.Array"
    ) as excinfo:
        ctx_table.sql("select not_an_array_window(a) over () from t").collect()
    _assert_plain_error(excinfo)


class _NotAPlanRule:
    def try_optimize(self, plan):
        return "not a plan"


def test_optimizer_rule_returning_non_plan_raises():
    state = SessionState().add_optimizer_rule(_NotAPlanRule())
    ctx = SessionContext(session_state=state)
    ctx.register_record_batches(
        "t", [[pa.RecordBatch.from_arrays([pa.array([1, 2, 3])], names=["a"])]]
    )

    with pytest.raises(Exception, match="LogicalPlan") as excinfo:
        ctx.sql("select a from t").collect()
    _assert_plain_error(excinfo)


_WINDOW_FLAGS = [
    "is_causal",
    "supports_bounded_execution",
    "uses_window_frame",
    "include_rank",
]


class _RankEvaluator(WindowEvaluator):
    """Dense rank via evaluate_all_with_rank: only reached when include_rank()."""

    def include_rank(self):
        return True

    def evaluate_all_with_rank(self, num_rows, ranks_in_partition):
        return pa.array(
            [
                rank
                for rank, (start, end) in enumerate(ranks_in_partition, start=1)
                for _ in range(start, end)
            ],
            pa.int64(),
        )


def _raising_flag(flag):
    def raise_(self):
        raise ValueError(f"{flag} exploded")

    return type(f"Raising_{flag}", (_RankEvaluator,), {flag: raise_})()


def _register_rank(ctx, evaluator):
    ctx.register_udwf(
        udwf(evaluator, [pa.int64()], pa.int64(), volatility="immutable", name="rnk")
    )


@pytest.fixture
def ctx_ranked(ctx):
    ctx.register_record_batches(
        "r", [[pa.RecordBatch.from_arrays([pa.array([1, 1, 2, 3])], names=["a"])]]
    )
    return ctx


def test_udwf_flags_are_used(ctx_ranked):
    _register_rank(ctx_ranked, _RankEvaluator())
    rb = ctx_ranked.sql("select rnk(a) over (order by a) as k from r order by a")
    assert rb.to_arrow_table().column("k").to_pylist() == [1, 1, 2, 3]


@pytest.mark.parametrize("flag", _WINDOW_FLAGS)
def test_udwf_flag_raising_fails_the_query(ctx_ranked, flag):
    # These used to be read with unwrap_or(false): the exception was dropped and
    # the window ran as if the flag were False.
    _register_rank(ctx_ranked, _raising_flag(flag))
    with pytest.raises(Exception, match=f"{flag} exploded") as excinfo:
        ctx_ranked.sql("select rnk(a) over (order by a) from r").collect()
    _assert_plain_error(excinfo)


def test_udwf_flag_returning_non_bool_fails_the_query(ctx_ranked):
    evaluator = type("NonBool", (_RankEvaluator,), {"include_rank": lambda self: "yes"})
    _register_rank(ctx_ranked, evaluator())
    with pytest.raises(Exception, match="bool") as excinfo:
        ctx_ranked.sql("select rnk(a) over (order by a) from r").collect()
    _assert_plain_error(excinfo)
