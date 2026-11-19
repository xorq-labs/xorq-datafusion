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
