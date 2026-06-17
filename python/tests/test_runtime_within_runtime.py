"""
Regression + property tests for the nested-runtime panic.

The panic:

    Cannot start a runtime from within a runtime. This happens because a
    function (like `block_on`) attempted to block the current thread while the
    thread is being used to drive asynchronous tasks.

Root cause
----------
`SessionContext` methods that execute or plan (`sql`, `collect`, `table`, ...)
call `wait_for_future`, which used to do `runtime.block_on(fut)` on the single,
process-wide tokio runtime (see `src/utils.rs::get_runtime`).

A Python `TableProvider`'s `scan` / `schema` is invoked *inside* that outer
`block_on` (see `src/provider.rs`). If that Python code reaches back into
another `SessionContext` and triggers another `block_on` on the same runtime,
tokio panics.

The fix detects the in-runtime case via `Handle::try_current()` and uses
`tokio::task::block_in_place` + `Handle::block_on` instead of nesting a runtime.
These tests pin the resulting contract: a re-entrant provider returns the same
rows the inner context would, at arbitrary data sizes and nesting depths.
"""

import collections
import concurrent.futures
import threading

import pyarrow as pa
import pytest
from hypothesis import HealthCheck, given, settings
from xorq_datafusion import SessionContext, udf

from tests.strategies import int64_table_values, nesting_depth, worker_count

_SCHEMA = pa.schema([("id", pa.int64())])
_TIMEOUT = 15


def _run_with_timeout(fn, timeout=_TIMEOUT):
    """
    Run fn on a daemon thread; fail (not hang) if it doesn't finish in time.

    A nested-runtime regression would manifest as a hang, not a clean error, so
    every test that drives a re-entrant scan goes through this guard.
    """
    done = threading.Event()
    holder = {}

    def _inner():
        try:
            holder["result"] = fn()
        except Exception as exc:
            holder["error"] = exc
        finally:
            done.set()

    threading.Thread(target=_inner, daemon=True).start()
    if not done.wait(timeout=timeout):
        pytest.fail("timed out — likely nested-runtime hang or deadlock")
    if "error" in holder:
        raise holder["error"]
    return holder["result"]


def _register_values(ctx, name, values):
    """Register `values` as a one-column int64 table on `ctx`."""
    batch = pa.record_batch({"id": pa.array(values, type=pa.int64())}, schema=_SCHEMA)
    ctx.register_record_batches(name, [[batch]])


class _ScanReentrantProvider:
    """
    TableProvider whose `scan` re-queries another context.

    `scan` runs inside the outer context's `block_on`; calling `.collect()` on
    `src_ctx` issues another `block_on` on the same global tokio runtime.
    """

    def __init__(self, src_ctx, query):
        self.src_ctx = src_ctx
        self.query = query
        self._schema = _SCHEMA

    def schema(self):
        return self._schema

    def scan(self, filters=None):
        batches = self.src_ctx.sql(self.query).collect()
        return pa.RecordBatchReader.from_batches(self._schema, batches)


class _SchemaReentrantProvider(_ScanReentrantProvider):
    """
    Provider whose `schema` *also* re-enters the runtime.

    `schema()` is called during the outer context's planning, which itself runs
    inside `block_on`; resolving it via `src_ctx.sql(...)` re-enters there too.
    """

    def schema(self):
        return self.src_ctx.sql(self.query).schema()


class _TableMethodReentrantProvider:
    """
    Re-enters via `src_ctx.table(name)` rather than `sql()`.

    Exercises a different `wait_for_future` call site than the SQL path, so the
    fix is shown to cover the entry point, not one specific method.
    """

    def __init__(self, src_ctx, table_name):
        self.src_ctx = src_ctx
        self.table_name = table_name
        self._schema = _SCHEMA

    def schema(self):
        return self._schema

    def scan(self, filters=None):
        batches = self.src_ctx.table(self.table_name).collect()
        return pa.RecordBatchReader.from_batches(self._schema, batches)


class _RaisingScanProvider:
    """Provider whose `scan` raises, from inside the outer context's block_on."""

    def __init__(self, exc):
        self.exc = exc

    def schema(self):
        return _SCHEMA

    def scan(self, filters=None):
        raise self.exc


def _ids(rows):
    """Multiset of the `id` column across collected batches."""
    return collections.Counter(v for b in rows for v in b.column("id").to_pylist())


def test_register_table_provider_nested_runtime():
    """
    Fixed regression anchor: before the fix this panicked with
    "Cannot start a runtime from within a runtime".
    """
    inner = SessionContext()
    _register_values(inner, "inner_t", [1, 2])

    outer = SessionContext()
    outer.register_table_provider(
        "reentrant", _ScanReentrantProvider(inner, "select id from inner_t")
    )

    result = outer.sql("select * from reentrant").to_pandas()
    assert sorted(result["id"].tolist()) == [1, 2]


@given(int64_table_values())
@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_reentrant_scan_returns_inner_rows(values):
    """
    Scanning through a re-entrant provider yields the inner context's exact
    multiset of rows — no panic, no loss, no duplication.
    """
    inner = SessionContext()
    _register_values(inner, "inner_t", values)

    outer = SessionContext()
    outer.register_table_provider(
        "reentrant", _ScanReentrantProvider(inner, "select id from inner_t")
    )

    rows = outer.sql("select * from reentrant").collect()
    assert _ids(rows) == collections.Counter(values)


@given(int64_table_values())
@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_reentrant_schema_returns_inner_rows(values):
    """
    A provider whose schema() re-enters during planning (not just scan) still
    resolves and returns the inner rows.
    """
    inner = SessionContext()
    _register_values(inner, "inner_t", values)

    outer = SessionContext()
    outer.register_table_provider(
        "reentrant", _SchemaReentrantProvider(inner, "select id from inner_t")
    )

    rows = outer.sql("select * from reentrant").collect()
    assert _ids(rows) == collections.Counter(values)


@given(int64_table_values(max_rows=500), nesting_depth)
@settings(max_examples=30, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_nested_reentrant_chain_preserves_rows(values, depth):
    """
    A depth-k chain of re-entrant providers nests block_in_place k levels
    deep; the rows still propagate unchanged from the base context.
    """
    base = SessionContext()
    _register_values(base, "t", values)

    ctx = base
    for _ in range(depth):
        nxt = SessionContext()
        nxt.register_table_provider(
            "t", _ScanReentrantProvider(ctx, "select id from t")
        )
        ctx = nxt

    rows = ctx.sql("select * from t").collect()
    assert _ids(rows) == collections.Counter(values)


def _assert_runtime_still_usable():
    """
    A fresh, unrelated query must succeed after a failed re-entrant scan —
    a failure must not poison the shared runtime.
    """
    ctx = SessionContext()
    _register_values(ctx, "t", [1, 2, 3])
    assert _ids(ctx.sql("select id from t").collect()) == collections.Counter([1, 2, 3])


def _assert_ctx_still_usable(outer):
    """
    The context that hit the failure must itself recover: a working table
    registered on it queries fine (not left in a poisoned borrow state).
    """
    _register_values(outer, "ok", [1, 2, 3])
    assert _ids(outer.sql("select id from ok").collect()) == collections.Counter(
        [1, 2, 3]
    )


def test_reentrant_scan_exception_propagates():
    """
    An exception raised inside scan (mid block_on) surfaces as a Python error,
    does not hang, and leaves both a fresh context and the failing context
    usable — including re-running the same failing query.
    """
    outer = SessionContext()
    outer.register_table_provider(
        "boom", _RaisingScanProvider(RuntimeError("scan failed"))
    )

    with pytest.raises(RuntimeError, match="scan failed"):
        _run_with_timeout(lambda: outer.sql("select * from boom").collect())

    # the same failing query must fail cleanly again, not hang or change error
    with pytest.raises(RuntimeError, match="scan failed"):
        _run_with_timeout(lambda: outer.sql("select * from boom").collect())

    _assert_runtime_still_usable()
    _assert_ctx_still_usable(outer)


def test_reentrant_inner_query_error_propagates():
    """
    If the re-entered inner query itself errors (bad SQL), the error surfaces
    through the outer query without a hang, and both a fresh context and the
    failing context stay usable.
    """
    inner = SessionContext()
    _register_values(inner, "inner_t", [1, 2, 3])

    outer = SessionContext()
    outer.register_table_provider(
        "reentrant", _ScanReentrantProvider(inner, "select id from does_not_exist")
    )

    with pytest.raises(ValueError, match="not found"):
        _run_with_timeout(lambda: outer.sql("select * from reentrant").collect())

    _assert_runtime_still_usable()
    _assert_ctx_still_usable(outer)


@given(int64_table_values(max_rows=500), worker_count)
@settings(max_examples=20, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_concurrent_reentrant_scans(values, n):
    """
    N threads each drive an independent re-entrant scan concurrently. Every
    worker must return the correct rows with no nested-runtime hang.
    """
    expected = collections.Counter(values)
    barrier = threading.Barrier(n)

    def worker(_idx):
        inner = SessionContext()
        _register_values(inner, "inner_t", values)
        outer = SessionContext()
        outer.register_table_provider(
            "reentrant", _ScanReentrantProvider(inner, "select id from inner_t")
        )
        barrier.wait(timeout=_TIMEOUT)
        return outer.sql("select * from reentrant").collect()

    def run():
        with concurrent.futures.ThreadPoolExecutor(max_workers=n) as ex:
            futs = [ex.submit(worker, i) for i in range(n)]
            done, pending = concurrent.futures.wait(futs, timeout=_TIMEOUT)
        assert not pending, f"{len(pending)} concurrent re-entrant scans timed out"
        return [f.result() for f in done]

    for rows in _run_with_timeout(run, timeout=_TIMEOUT * 2):
        assert _ids(rows) == expected


@given(int64_table_values())
@settings(max_examples=30, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_reentrant_via_table_method_returns_inner_rows(values):
    """
    Re-entering through ctx.table() (a different wait_for_future call site
    than sql()) still returns the inner rows.
    """
    inner = SessionContext()
    _register_values(inner, "inner_t", values)

    outer = SessionContext()
    outer.register_table_provider("r", _TableMethodReentrantProvider(inner, "inner_t"))

    rows = _run_with_timeout(lambda: outer.sql("select * from r").collect())
    assert _ids(rows) == collections.Counter(values)


@given(int64_table_values())
@settings(max_examples=30, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_outer_union_all_reenters_per_arm(values):
    """
    An outer UNION ALL scans the re-entrant provider twice, so scan re-enters
    twice within one outer block_on; every row must appear exactly twice.
    """
    inner = SessionContext()
    _register_values(inner, "inner_t", values)

    outer = SessionContext()
    outer.register_table_provider(
        "r", _ScanReentrantProvider(inner, "select id from inner_t")
    )

    rows = _run_with_timeout(
        lambda: outer.sql("select * from r UNION ALL select * from r").collect()
    )
    assert _ids(rows) == collections.Counter(values * 2)


@given(int64_table_values())
@settings(max_examples=30, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_reentrant_scan_via_outer_execute_stream(values):
    """
    Driving the outer query through execute_stream (wait_for_completion +
    spawn) instead of collect still re-enters cleanly and yields the inner rows.
    """
    inner = SessionContext()
    _register_values(inner, "inner_t", values)

    outer = SessionContext()
    outer.register_table_provider(
        "r", _ScanReentrantProvider(inner, "select id from inner_t")
    )

    def run():
        df = outer.sql("select * from r")
        return [b.to_pyarrow() for b in df.execute_stream()]

    assert _ids(_run_with_timeout(run)) == collections.Counter(values)


@given(int64_table_values(max_rows=300))
@settings(max_examples=30, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_udf_reentry_returns_inner_count(values):
    """
    A scalar UDF whose body re-enters another context (a UDF callback site,
    not a TableProvider) runs without a nested-runtime panic. Each output cell
    equals the inner row count.
    """
    inner = SessionContext()
    _register_values(inner, "inner_t", values)

    def body(arr):
        n = inner.sql("select id from inner_t").count()
        return pa.array([n] * len(arr), type=pa.int64())

    fn = udf(
        body,
        input_types=[pa.int64()],
        return_type=pa.int64(),
        volatility="volatile",
        name="reentry_udf",
    )
    outer = SessionContext()
    _register_values(outer, "t", [1, 2, 3])
    outer.register_udf(fn)

    rows = _run_with_timeout(
        lambda: outer.sql("select reentry_udf(id) v from t").collect()
    )
    table = pa.Table.from_batches(rows)
    assert table.column("v").to_pylist() == [len(values)] * 3


@given(int64_table_values(max_rows=100), int64_table_values(max_rows=100))
@settings(max_examples=30, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_join_two_reentrant_providers(values_a, values_b):
    """
    An outer join of two *different* re-entrant providers re-enters two
    distinct inner contexts within one outer block_on (the join sides may scan
    in parallel). The match count must equal the exact join cardinality,
    sum_k freq_a(k) * freq_b(k).
    """
    inner_a = SessionContext()
    _register_values(inner_a, "t", values_a)
    inner_b = SessionContext()
    _register_values(inner_b, "t", values_b)

    outer = SessionContext()
    outer.register_table_provider(
        "a", _ScanReentrantProvider(inner_a, "select id from t")
    )
    outer.register_table_provider(
        "b", _ScanReentrantProvider(inner_b, "select id from t")
    )

    ca, cb = collections.Counter(values_a), collections.Counter(values_b)
    expected = sum(ca[k] * cb[k] for k in ca)

    rows = _run_with_timeout(
        lambda: outer.sql("select count(*) c from a join b on a.id = b.id").collect()
    )
    assert rows[0].column("c")[0].as_py() == expected


@given(int64_table_values(max_rows=500), worker_count)
@settings(max_examples=20, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_concurrent_reentry_shared_inner_ctx(values, n):
    """
    N outer contexts re-enter one *shared* inner context concurrently. Beyond
    the nested-runtime guarantee this stresses the inner context's shared (&self)
    borrow under simultaneous nested block_on calls.
    """
    inner = SessionContext()
    _register_values(inner, "inner_t", values)
    expected = collections.Counter(values)
    barrier = threading.Barrier(n)

    def worker(_idx):
        outer = SessionContext()
        outer.register_table_provider(
            "r", _ScanReentrantProvider(inner, "select id from inner_t")
        )
        barrier.wait(timeout=_TIMEOUT)
        return outer.sql("select * from r").collect()

    def run():
        with concurrent.futures.ThreadPoolExecutor(max_workers=n) as ex:
            futs = [ex.submit(worker, i) for i in range(n)]
            done, pending = concurrent.futures.wait(futs, timeout=_TIMEOUT)
        assert not pending, f"{len(pending)} shared-inner re-entrant scans timed out"
        return [f.result() for f in done]

    for rows in _run_with_timeout(run, timeout=_TIMEOUT * 2):
        assert _ids(rows) == expected
