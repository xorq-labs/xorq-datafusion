"""Property-based concurrency / re-entrancy tests for batchcorder.StreamCache
feeding a xorq_datafusion SessionContext.

Background (issue #37): `SessionContext.sql(...)` used to take `&mut self`, so a
re-entrant or concurrent `sql()`/DDL on a context whose previous StreamCache
scan was still draining raised `RuntimeError: Already borrowed`. The fix makes
those methods take `&self` (shared borrows). These tests pin the resulting
contracts under the StreamCache usage patterns that surfaced the bug:

- re-entrant DROP VIEW from inside a result reader's generator `finally`;
- many threads issuing sql() + DDL against one shared context;
- bounded (`max_readers`) StreamCache fan-out, both read directly and scanned
  through independent SessionContexts;
- deterministic `max_readers` cap / replay contracts.

All concurrent tests use a timeout guard: a hang (deadlock) fails fast instead
of stalling the suite. `batchcorder` is optional, so every test skips cleanly
without it.
"""

import collections
import concurrent.futures
import threading

import pyarrow as pa
import pytest
from hypothesis import HealthCheck, given, settings

import xorq_datafusion as xdf
from tests.strategies import int64_stream_data, limit_value, worker_count

_TIMEOUT = 15
_SCHEMA = pa.schema([("x", pa.int64())])


def _make_stream_cache(values, batch_size, *, max_readers=None):
    """StreamCache over a single int64 column, chunked into batch_size rows."""
    # Lazy import keeps batchcorder optional (callers guard with importorskip).
    from batchcorder import StreamCache  # noqa: PLC0415

    def _batches():
        for start in range(0, len(values), batch_size):
            chunk = values[start : start + batch_size]
            yield pa.record_batch(
                {"x": pa.array(chunk, type=pa.int64())}, schema=_SCHEMA
            )

    reader = pa.RecordBatchReader.from_batches(_SCHEMA, _batches())
    if max_readers is None:
        return StreamCache(reader)
    return StreamCache(reader, max_readers=max_readers)


def _run_with_timeout(fn, timeout=_TIMEOUT):
    """Run fn on a daemon thread; fail (not hang) if it doesn't finish in time."""
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
        pytest.fail("timed out — likely deadlock or borrow stall")
    if "error" in holder:
        raise holder["error"]
    return holder["result"]


# ---------------------------------------------------------------------------
# Re-entrant teardown: DROP VIEW from inside a result reader's `finally`
# ---------------------------------------------------------------------------


@given(int64_stream_data(), limit_value)
@settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_drop_view_during_reader_teardown_does_not_raise(data, limit):
    """Re-entrant ctx.sql('DROP VIEW') while the reader drains: no error,
    correct row count, and the view is actually gone afterwards.

    Mirrors xorq's teardown: the result RecordBatchReader runs cleanup in its
    generator's `finally`, re-entering the same context.
    """
    pytest.importorskip("batchcorder")
    values, batch_size = data
    ctx = xdf.SessionContext()
    ctx.register_record_batch_reader("t", _make_stream_cache(values, batch_size))
    ctx.sql("CREATE VIEW v AS SELECT x FROM t").collect()

    df = ctx.sql(f"SELECT x FROM v LIMIT {limit}")
    schema = df.schema()

    def gen():
        try:
            for batch in df.execute_stream():
                yield batch.to_pyarrow().cast(schema)
        finally:
            # Re-enter the context while the reader is still being torn down.
            ctx.sql("DROP VIEW v").collect()

    reader = pa.RecordBatchReader.from_batches(schema, gen())
    table = _run_with_timeout(reader.read_all)

    assert table.num_rows == min(limit, len(values))
    assert not ctx.table_exist("v")


# ---------------------------------------------------------------------------
# Concurrent shared context: many threads, one StreamCache-backed context
# ---------------------------------------------------------------------------


@given(int64_stream_data(max_rows=2000), worker_count)
@settings(max_examples=10, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_concurrent_sql_and_ddl_no_already_borrowed(data, n):
    """N threads each create a private view over a shared StreamCache table,
    aggregate it, and drop it. No 'Already borrowed'; every aggregate is correct.

    This is the concurrency shape that made the latent `&mut self` borrow
    deterministic: one thread holds the context borrow across the GIL-releasing
    wait while another re-borrows.
    """
    pytest.importorskip("batchcorder")
    values, batch_size = data
    expected_sum = sum(values) if values else None
    expected_cnt = len(values)

    ctx = xdf.SessionContext()
    ctx.register_record_batch_reader("t", _make_stream_cache(values, batch_size))
    barrier = threading.Barrier(n)

    def worker(idx):
        view = f"v_{idx}"
        barrier.wait(timeout=_TIMEOUT)
        results = []
        for _ in range(5):
            ctx.sql(f"CREATE VIEW {view} AS SELECT x FROM t").collect()
            rb = ctx.sql(f"SELECT sum(x) AS s, count(x) AS c FROM {view}").collect()[0]
            ctx.sql(f"DROP VIEW {view}").collect()
            results.append((rb.column("s")[0].as_py(), rb.column("c")[0].as_py()))
        return results

    def run():
        with concurrent.futures.ThreadPoolExecutor(max_workers=n) as ex:
            futs = [ex.submit(worker, i) for i in range(n)]
            done, pending = concurrent.futures.wait(futs, timeout=_TIMEOUT)
        assert not pending, f"{len(pending)} workers timed out — likely deadlock"
        return [f.result() for f in done]

    for per_worker in _run_with_timeout(run, timeout=_TIMEOUT * 2):
        for got_sum, got_cnt in per_worker:
            assert got_sum == expected_sum
            assert got_cnt == expected_cnt


# ---------------------------------------------------------------------------
# max_readers: deterministic cap / replay contracts
#
# The documented reader(from_start=True) "batch 0 already evicted" ValueError is
# NOT tested here: it is unreachable through the public API (the reader cap
# blocks requesting another from_start reader once all slots are allocated,
# which is the only way to land on an evicted batch 0). batchcorder's own suite
# owns it.
# ---------------------------------------------------------------------------


def test_exceeding_max_readers_raises():
    """Requesting reader #(n+1) after n created raises ValueError."""
    pytest.importorskip("batchcorder")
    cache = _make_stream_cache([0, 1, 2, 3, 4], 2, max_readers=2)
    cache.reader()
    cache.reader()
    with pytest.raises(ValueError, match="Maximum number of readers"):
        cache.reader()


def test_dropped_reader_does_not_free_slot():
    """Dropping a reader does not return its slot; the cap still holds."""
    pytest.importorskip("batchcorder")
    cache = _make_stream_cache([0, 1, 2, 3, 4], 2, max_readers=2)
    r = cache.reader()
    del r
    cache.reader()  # second (and final) slot
    with pytest.raises(ValueError, match="Maximum number of readers"):
        cache.reader()


def test_max_readers_one_single_reader_replays():
    """Boundary max_readers=1: the single reader replays the full stream."""
    pytest.importorskip("batchcorder")
    cache = _make_stream_cache([0, 1, 2, 3, 4], 2, max_readers=1)
    table = pa.RecordBatchReader.from_stream(cache.reader()).read_all()
    assert table.column("x").to_pylist() == [0, 1, 2, 3, 4]
    with pytest.raises(ValueError, match="Maximum number of readers"):
        cache.reader()


def test_all_slots_replay_after_upstream_exhausted():
    """All n readers created up front each replay the full stream, and the
    upstream is consumed exactly once (upstream_exhausted becomes True)."""
    pytest.importorskip("batchcorder")
    values = [0, 1, 2, 3, 4]
    cache = _make_stream_cache(values, 2, max_readers=3)
    readers = [cache.reader() for _ in range(3)]
    for r in readers:
        table = pa.RecordBatchReader.from_stream(r).read_all()
        assert table.column("x").to_pylist() == values
    assert cache.upstream_exhausted


def test_undersubscribed_cache_retains_all_batches():
    """With fewer live readers than max_readers, eviction never starts: a reader
    created after others have drained still replays from batch 0."""
    pytest.importorskip("batchcorder")
    values = [0, 1, 2, 3, 4]
    cache = _make_stream_cache(values, 2, max_readers=5)
    for _ in range(2):
        pa.RecordBatchReader.from_stream(cache.reader()).read_all()
    later = pa.RecordBatchReader.from_stream(cache.reader(from_start=True)).read_all()
    assert later.column("x").to_pylist() == values


def test_max_readers_must_cover_scan_count():
    """Each DataFusion scan of the registered cache consumes one reader slot, so
    a query that scans the table k times needs max_readers >= k.

    This is the xorq integration footgun: a bound sized for a single scan
    deadlocks/errors a multi-scan plan. max_readers=1 fails a 2-scan UNION ALL;
    max_readers=2 succeeds.
    """
    pytest.importorskip("batchcorder")
    values = [0, 1, 2, 3, 4]
    union_all = "SELECT x FROM t UNION ALL SELECT x FROM t"

    ctx1 = xdf.SessionContext()
    ctx1.register_record_batch_reader("t", _make_stream_cache(values, 2, max_readers=1))
    with pytest.raises(ValueError, match="Maximum number of readers"):
        ctx1.sql(union_all).collect()

    ctx2 = xdf.SessionContext()
    ctx2.register_record_batch_reader("t", _make_stream_cache(values, 2, max_readers=2))
    table = pa.Table.from_batches(ctx2.sql(union_all).collect(), schema=_SCHEMA)
    assert sorted(table.column("x").to_pylist()) == sorted(values * 2)


# ---------------------------------------------------------------------------
# max_readers: bounded fan-out under concurrency
# ---------------------------------------------------------------------------


@given(int64_stream_data(), worker_count)
@settings(max_examples=15, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_bounded_readers_replay_full_stream(data, n):
    """A StreamCache(max_readers=n) hands out exactly n readers; each, consumed
    concurrently, replays the entire stream.

    All n readers are created before any is consumed — eviction only begins once
    every slot is allocated, so batch 0 is retained for every reader.
    """
    pytest.importorskip("batchcorder")

    values, batch_size = data
    cache = _make_stream_cache(values, batch_size, max_readers=n)
    readers = [cache.reader(from_start=True) for _ in range(n)]
    expected = collections.Counter(values)

    def drain(reader):
        return pa.RecordBatchReader.from_stream(reader).read_all()

    def run():
        with concurrent.futures.ThreadPoolExecutor(max_workers=n) as ex:
            futs = [ex.submit(drain, r) for r in readers]
            done, pending = concurrent.futures.wait(futs, timeout=_TIMEOUT)
        assert not pending, f"{len(pending)} readers timed out"
        return [f.result() for f in done]

    for table in _run_with_timeout(run):
        assert collections.Counter(table.column("x").to_pylist()) == expected


@given(int64_stream_data(max_rows=2000), worker_count)
@settings(max_examples=10, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_bounded_fanout_through_independent_contexts(data, n):
    """N independent SessionContexts each scan one shared, bounded cache.

    Each single-scan query consumes exactly one of the n reader slots, so
    max_readers == n is satisfied. Mirrors xorq's RemoteTable fan-out where
    bounded caches are scanned through datafusion. Every query must return the
    correct aggregate with no eviction/borrow error.
    """
    pytest.importorskip("batchcorder")

    values, batch_size = data
    expected_sum = sum(values) if values else None
    expected_cnt = len(values)
    cache = _make_stream_cache(values, batch_size, max_readers=n)
    barrier = threading.Barrier(n)

    def worker(_idx):
        ctx = xdf.SessionContext()
        ctx.register_record_batch_reader("t", cache)
        barrier.wait(timeout=_TIMEOUT)
        return ctx.sql("SELECT sum(x) AS s, count(x) AS c FROM t").collect()[0]

    def run():
        with concurrent.futures.ThreadPoolExecutor(max_workers=n) as ex:
            futs = [ex.submit(worker, i) for i in range(n)]
            done, pending = concurrent.futures.wait(futs, timeout=_TIMEOUT)
        assert not pending, f"{len(pending)} fan-out queries timed out"
        return [f.result() for f in done]

    for rb in _run_with_timeout(run, timeout=_TIMEOUT * 2):
        assert rb.column("s")[0].as_py() == expected_sum
        assert rb.column("c")[0].as_py() == expected_cnt
