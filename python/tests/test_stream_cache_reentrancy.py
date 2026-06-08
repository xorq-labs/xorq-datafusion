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
  through independent SessionContexts.

All tests use a timeout guard: a hang (deadlock) fails fast instead of stalling
the suite. `batchcorder` is optional, so every test skips cleanly without it.
"""

import collections
import concurrent.futures
import threading

import pyarrow as pa
import pytest
from hypothesis import HealthCheck, given, settings

from tests.strategies import int64_stream_data, limit_value, worker_count


_TIMEOUT = 15
_SCHEMA = pa.schema([("x", pa.int64())])


def _make_stream_cache(values, batch_size, *, max_readers=None):
    """StreamCache over a single int64 column, chunked into batch_size rows."""
    from batchcorder import StreamCache

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
        except Exception as exc:  # noqa: BLE001
            holder["error"] = exc
        finally:
            done.set()

    threading.Thread(target=_inner, daemon=True).start()
    if not done.wait(timeout=timeout):
        pytest.fail("timed out — likely deadlock or borrow stall")
    if "error" in holder:
        raise holder["error"]
    return holder["result"]


class TestReentrantTeardown:
    """A DROP VIEW issued from a result reader's own `finally` must not panic."""

    @given(int64_stream_data(), limit_value)
    @settings(
        max_examples=25, deadline=None, suppress_health_check=[HealthCheck.too_slow]
    )
    def test_drop_view_during_reader_teardown_does_not_raise(self, data, limit):
        """Re-entrant ctx.sql('DROP VIEW') while the reader drains: no error,
        correct row count, and the view is actually gone afterwards.

        Mirrors xorq's teardown: the result RecordBatchReader runs cleanup in
        its generator's `finally`, re-entering the same context.
        """
        pytest.importorskip("batchcorder")
        import xorq_datafusion as xdf

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


class TestConcurrentSharedContext:
    """Many threads sharing one context (StreamCache-backed) must not panic."""

    @given(int64_stream_data(max_rows=2000), worker_count)
    @settings(
        max_examples=10, deadline=None, suppress_health_check=[HealthCheck.too_slow]
    )
    def test_concurrent_sql_and_ddl_no_already_borrowed(self, data, n):
        """N threads each create a private view over a shared StreamCache table,
        aggregate it, and drop it. No 'Already borrowed'; every aggregate is
        correct.

        This is the concurrency shape that made the latent `&mut self` borrow
        deterministic: one thread holds the context borrow across the
        GIL-releasing wait while another re-borrows.
        """
        pytest.importorskip("batchcorder")
        import xorq_datafusion as xdf

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
                rb = ctx.sql(
                    f"SELECT sum(x) AS s, count(x) AS c FROM {view}"
                ).collect()[0]
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


class TestMaxReadersFanout:
    """Bounded (`max_readers`) StreamCache replay must stay correct concurrently."""

    @given(int64_stream_data(), worker_count)
    @settings(
        max_examples=15, deadline=None, suppress_health_check=[HealthCheck.too_slow]
    )
    def test_bounded_readers_replay_full_stream(self, data, n):
        """A StreamCache(max_readers=n) hands out exactly n readers; each,
        consumed concurrently, replays the entire stream.

        All n readers are created before any is consumed — eviction only begins
        once every slot is allocated, so batch 0 is retained for every reader.
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
    @settings(
        max_examples=10, deadline=None, suppress_health_check=[HealthCheck.too_slow]
    )
    def test_bounded_fanout_through_independent_contexts(self, data, n):
        """N independent SessionContexts each scan one shared, bounded cache.

        Each single-scan query consumes exactly one of the n reader slots, so
        max_readers == n is satisfied. Mirrors xorq's RemoteTable fan-out where
        bounded caches are scanned through datafusion. Every query must return
        the correct aggregate with no eviction/borrow error.
        """
        pytest.importorskip("batchcorder")

        values, batch_size = data
        expected_sum = sum(values) if values else None
        expected_cnt = len(values)
        cache = _make_stream_cache(values, batch_size, max_readers=n)
        barrier = threading.Barrier(n)

        def worker(_idx):
            import xorq_datafusion as xdf

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
