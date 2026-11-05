"""Table providers loaded over the datafusion-python FFI protocol.

The batchcorder tests are skipped unless the ``batchcorder_datafusion`` wheel
is installed, e.g. with
``maturin develop --uv -m ../multirecord/crates/batchcorder-datafusion-py/Cargo.toml``.
FFI structs are only compatible within one DataFusion major version, so it
must be built against the same DataFusion major as xorq-datafusion.
"""

import subprocess
import sys

import pyarrow as pa
import pytest

from xorq_datafusion import SessionContext

try:
    from batchcorder_datafusion import TeeTableProvider
except ImportError:
    TeeTableProvider = None

requires_batchcorder = pytest.mark.skipif(
    TeeTableProvider is None, reason="batchcorder_datafusion is not installed"
)


N_ROWS = 1000
CHUNK = 50


def _batches() -> list[pa.RecordBatch]:
    out = []
    for start in range(0, N_ROWS, CHUNK):
        x = list(range(start, start + CHUNK))
        out.append(pa.record_batch({"k": [v % 7 for v in x], "x": x}))
    return out


def _schema() -> pa.Schema:
    return _batches()[0].schema


def _provider(**kwargs):
    reader = pa.RecordBatchReader.from_batches(_schema(), _batches())
    return TeeTableProvider(reader, **kwargs)


def _tee_ctx(provider) -> SessionContext:
    # Keep the context alive until the query finishes: over FFI the provider
    # only holds a weak reference to the host session.
    ctx = SessionContext()
    ctx.register_table_provider("t", provider)
    return ctx


def _reference_result(sql: str) -> pa.Table:
    ctx = SessionContext()
    ctx.register_record_batches("t", [_batches()])
    return ctx.sql(sql).to_arrow_table()


def test_session_exposes_logical_extension_codec():
    capsule = SessionContext().__datafusion_logical_extension_codec__()
    assert type(capsule).__name__ == "PyCapsule"
    assert "datafusion_logical_extension_codec" in repr(capsule)


class _NotACapsule:
    def __datafusion_table_provider__(self, session):
        return object()


class _WrongCapsule:
    def __datafusion_table_provider__(self, session):
        # Any capsule with a different name must be rejected.
        return session


def test_ffi_provider_must_return_capsule():
    with pytest.raises(TypeError, match="must return a PyCapsule"):
        SessionContext().register_table_provider("t", _NotACapsule())


def test_ffi_provider_capsule_name_is_checked():
    with pytest.raises(ValueError, match="datafusion_table_provider"):
        SessionContext().register_table_provider("t", _WrongCapsule())


QUERIES = [
    pytest.param("select count(*) as c, sum(x) as s from t", 1, id="single-scan"),
    pytest.param(
        "select a.k, count(*) as c from t a join t b on a.k = b.k group by a.k order by a.k",
        2,
        id="self-join",
    ),
    pytest.param(
        "with c as (select k, x from t where x % 2 = 0) "
        "select (select count(*) from c) as n, (select sum(x) from c) as s, "
        "(select max(k) from c) as m",
        3,
        id="cte-x3",
    ),
    pytest.param(
        "select count(*) as c from (select x from t union all select x from t where false)",
        1,
        id="pruned-branch",
    ),
]


@requires_batchcorder
@pytest.mark.parametrize(("sql", "scans"), QUERIES)
def test_tee_provider_matches_reference_with_exact_fanout(sql, scans):
    provider = _provider()
    ctx = _tee_ctx(provider)
    assert ctx.table_exist("t")
    result = ctx.sql(sql).to_arrow_table()
    assert result.equals(_reference_result(sql))
    assert provider.scans_planned == scans
    assert provider.scans_executed == scans
    assert provider.evicted_count == provider.ingested_count == N_ROWS // CHUNK


@requires_batchcorder
def test_tee_provider_execute_stream():
    provider = _provider()
    ctx = _tee_ctx(provider)
    sql = "select a.k, count(*) as c from t a join t b on a.k = b.k group by a.k order by a.k"
    batches = [batch.to_pyarrow() for batch in ctx.sql(sql).execute_stream()]
    result = pa.Table.from_batches(batches)
    assert result.equals(_reference_result(sql))
    assert provider.scans_executed == 2


@requires_batchcorder
def test_sealed_tee_provider_rejects_second_query():
    ctx = _tee_ctx(_provider())
    ctx.sql("select sum(x) from t").collect()
    with pytest.raises(Exception, match="register a new provider"):
        ctx.sql("select sum(x) from t").collect()


@requires_batchcorder
def test_unbounded_tee_provider_can_be_queried_repeatedly():
    ctx = _tee_ctx(_provider(bounding="unbounded"))
    sql = "select k, sum(x) as s from t group by k order by k"
    expected = _reference_result(sql)
    for _ in range(3):
        assert ctx.sql(sql).to_arrow_table().equals(expected)


# A Python-generator upstream read concurrently by several DataFusion scans.
# Every pull needs the GIL, so this fails (by timeout, in a subprocess) if the
# host holds the GIL while waiting on a foreign stream.
_PYTHON_UPSTREAM_SCRIPT = """
import pyarrow as pa
from xorq_datafusion import SessionContext
from batchcorder_datafusion import TeeTableProvider

schema = pa.schema([("k", pa.int64()), ("x", pa.int64())])

def gen():
    for b in range(200):
        x = list(range(b * 10, (b + 1) * 10))
        yield pa.record_batch({"k": [v % 5 for v in x], "x": x}, schema=schema)

provider = TeeTableProvider(pa.RecordBatchReader.from_batches(schema, gen()))
ctx = SessionContext()
ctx.register_table_provider("t", provider)
out = ctx.sql(
    "select (select count(*) from t) as n, (select sum(x) from t) as s, "
    "(select count(*) from t a join t b on a.x = b.x) as j"
).to_pydict()
assert out == {"n": [2000], "s": [sum(range(2000))], "j": [2000]}, out
assert provider.scans_planned == 4, provider.scans_planned
print("ok")
"""


@requires_batchcorder
def test_tee_provider_python_upstream_concurrent_scans_do_not_deadlock():
    try:
        proc = subprocess.run(
            [sys.executable, "-c", _PYTHON_UPSTREAM_SCRIPT],
            timeout=60,
            check=False,
            capture_output=True,
            text=True,
        )
    except subprocess.TimeoutExpired:
        pytest.fail("deadlock: concurrent scans over a Python upstream hung")
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "ok"
