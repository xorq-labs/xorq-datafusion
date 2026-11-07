import pyarrow as pa
import pytest

from xorq_datafusion import SessionConfig, SessionContext, SessionState
from xorq_datafusion._internal import ml as _ml


@pytest.fixture
def df(ctx):
    batch = pa.record_batch({"a": [1, 2, 3], "b": [4.0, 5.0, 6.0]})
    ctx.register_record_batches("t", [[batch]])
    return ctx.sql("SELECT a, b FROM t WHERE a > 1")


def test_logical_plan_accessors(df):
    logical = df.logical_plan().display_indent()
    optimized = df.optimized_logical_plan().display_indent()
    assert "Filter" in logical
    assert "TableScan: t" in optimized


@pytest.mark.parametrize(
    "make_ctx",
    [
        SessionContext,
        lambda: SessionContext(config=SessionConfig()),
        lambda: SessionContext(session_state=SessionState()),
        lambda: SessionContext(
            session_state=SessionState().add_optimizer_rule(_IdentityRule())
        ),
    ],
    ids=["default", "config", "session_state", "add_optimizer_rule"],
)
def test_every_constructor_installs_ml(make_ctx):
    _ml.ensure_ml_session(make_ctx().sql("SELECT 1"))


def test_session_without_ml_is_refused():
    df = _ml._session_context_without_ml(None).sql("SELECT 1")
    with pytest.raises(ValueError, match="no ML planner"):
        _ml.ensure_ml_session(df)


class _IdentityRule:
    def try_optimize(self, plan):
        return plan
