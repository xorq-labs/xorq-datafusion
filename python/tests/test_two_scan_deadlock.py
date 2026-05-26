"""Regression test: two-scan query over StreamCache must not deadlock.

Root cause: PyRecordBatchProviderExec::execute() used to call Python::attach
(GIL acquisition) on a Tokio async worker thread. For two-scan queries, this
created a circular wait between async workers holding the GIL and
spawn_blocking threads holding batchcorder's DatasetInner mutex.

Fix: move all Python::attach calls into spawn_blocking so GIL acquisition
never happens on async worker threads.
"""

import concurrent.futures
import subprocess
import sys
import textwrap
import threading

import pyarrow as pa
import pytest


TIMEOUT_SECONDS = 8

_DEADLOCK_SCRIPT = textwrap.dedent("""\
    import pyarrow as pa
    import xorq_datafusion as xdf
    from batchcorder import StreamCache

    schema = pa.schema([("x", pa.int64())])
    cache = StreamCache(
        pa.RecordBatchReader.from_batches(
            schema,
            [pa.record_batch({"x": [i]}, schema=schema) for i in range(5)],
        )
    )
    ctx = xdf.SessionContext()
    ctx.register_record_batch_reader("t", cache)

    result = ctx.sql(
        \"\"\"
        WITH totals AS (SELECT sum(x) AS total FROM t),
             counts AS (SELECT count(x) AS cnt FROM t)
        SELECT total, cnt FROM totals CROSS JOIN counts
        \"\"\"
    ).collect()

    rb = result[0]
    total = rb.column("total")[0].as_py()
    cnt = rb.column("cnt")[0].as_py()
    assert total == 10, f"expected sum=10, got {total}"
    assert cnt == 5, f"expected cnt=5, got {cnt}"
    print("OK")
""")

_EXECUTE_STREAM_SCRIPT = textwrap.dedent("""\
    import pyarrow as pa
    import xorq_datafusion as xdf
    from batchcorder import StreamCache

    schema = pa.schema([("x", pa.int64())])
    cache = StreamCache(
        pa.RecordBatchReader.from_batches(
            schema,
            [pa.record_batch({"x": [i]}, schema=schema) for i in range(5)],
        )
    )
    ctx = xdf.SessionContext()
    ctx.register_record_batch_reader("t", cache)

    df = ctx.sql(
        \"\"\"
        WITH totals AS (SELECT sum(x) AS total FROM t),
             counts AS (SELECT count(x) AS cnt FROM t)
        SELECT total, cnt FROM totals CROSS JOIN counts
        \"\"\"
    )
    table = pa.Table.from_batches([b.to_pyarrow() for b in df.execute_stream()])
    total = table.column("total")[0].as_py()
    cnt = table.column("cnt")[0].as_py()
    assert total == 10, f"expected sum=10, got {total}"
    assert cnt == 5, f"expected cnt=5, got {cnt}"
    print("OK")
""")

_UNION_ALL_SCRIPT = textwrap.dedent("""\
    import pyarrow as pa
    import xorq_datafusion as xdf
    from batchcorder import StreamCache

    schema = pa.schema([("x", pa.int64())])
    cache = StreamCache(
        pa.RecordBatchReader.from_batches(
            schema,
            [pa.record_batch({"x": [i]}, schema=schema) for i in range(5)],
        )
    )
    ctx = xdf.SessionContext()
    ctx.register_record_batch_reader("t", cache)

    table = pa.Table.from_batches(
        ctx.sql("SELECT x FROM t UNION ALL SELECT x FROM t").collect()
    )
    assert table.num_rows == 10, f"expected 10 rows, got {table.num_rows}"
    assert sorted(table.column("x").to_pylist()) == sorted([0, 1, 2, 3, 4] * 2)
    print("OK")
""")

_THREE_SCAN_SCRIPT = textwrap.dedent("""\
    import pyarrow as pa
    import xorq_datafusion as xdf
    from batchcorder import StreamCache

    schema = pa.schema([("x", pa.int64())])
    cache = StreamCache(
        pa.RecordBatchReader.from_batches(
            schema,
            [pa.record_batch({"x": [i]}, schema=schema) for i in range(5)],
        )
    )
    ctx = xdf.SessionContext()
    ctx.register_record_batch_reader("t", cache)

    result = ctx.sql(
        \"\"\"
        WITH totals AS (SELECT sum(x) AS total FROM t),
             counts AS (SELECT count(x) AS cnt FROM t),
             maxes  AS (SELECT max(x) AS mx   FROM t)
        SELECT total, cnt, mx
          FROM totals CROSS JOIN counts CROSS JOIN maxes
        \"\"\"
    ).collect()

    rb = result[0]
    assert rb.column("total")[0].as_py() == 10
    assert rb.column("cnt")[0].as_py() == 5
    assert rb.column("mx")[0].as_py() == 4
    print("OK")
""")

_CONCURRENT_SCRIPT = textwrap.dedent("""\
    import concurrent.futures
    import threading
    import pyarrow as pa
    import xorq_datafusion as xdf
    from batchcorder import StreamCache

    N = 4
    schema = pa.schema([("x", pa.int64())])
    barrier = threading.Barrier(N)

    def worker(_idx):
        cache = StreamCache(
            pa.RecordBatchReader.from_batches(
                schema,
                [pa.record_batch({"x": [i]}, schema=schema) for i in range(5)],
            )
        )
        ctx = xdf.SessionContext()
        ctx.register_record_batch_reader("t", cache)
        barrier.wait()
        return ctx.sql(
            \"\"\"
            WITH totals AS (SELECT sum(x) AS total FROM t),
                 counts AS (SELECT count(x) AS cnt FROM t)
            SELECT total, cnt FROM totals CROSS JOIN counts
            \"\"\"
        ).collect()

    with concurrent.futures.ThreadPoolExecutor(max_workers=N) as executor:
        futs = [executor.submit(worker, i) for i in range(N)]
        results = [f.result() for f in concurrent.futures.as_completed(futs)]

    for batches in results:
        rb = batches[0]
        assert rb.column("total")[0].as_py() == 10, f"got {rb.column('total')[0].as_py()}"
        assert rb.column("cnt")[0].as_py() == 5, f"got {rb.column('cnt')[0].as_py()}"
    print("OK")
""")


def test_two_scan_no_deadlock_subprocess():
    """Two-scan query completes within timeout; TimeoutExpired means deadlock."""
    pytest.importorskip("batchcorder")
    proc = subprocess.run(
        [sys.executable, "-c", _DEADLOCK_SCRIPT],
        timeout=TIMEOUT_SECONDS,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, (
        f"script failed:\nstdout: {proc.stdout}\nstderr: {proc.stderr}"
    )
    assert proc.stdout.strip() == "OK"


def _run_script(script: str, timeout: int = TIMEOUT_SECONDS) -> None:
    """Run script in subprocess; fail with clear message on non-zero exit or timeout."""
    proc = subprocess.run(
        [sys.executable, "-c", script],
        timeout=timeout,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, (
        f"script failed:\nstdout: {proc.stdout}\nstderr: {proc.stderr}"
    )
    assert proc.stdout.strip() == "OK"


def test_execute_stream_no_deadlock_subprocess():
    """Two-scan via execute_stream in fresh process; TimeoutExpired means deadlock."""
    pytest.importorskip("batchcorder")
    _run_script(_EXECUTE_STREAM_SCRIPT)


def test_union_all_no_deadlock_subprocess():
    """UNION ALL two-scan in fresh process; TimeoutExpired means deadlock."""
    pytest.importorskip("batchcorder")
    _run_script(_UNION_ALL_SCRIPT)


def test_three_scan_no_deadlock_subprocess():
    """Three-CTE scan in fresh process; TimeoutExpired means deadlock."""
    pytest.importorskip("batchcorder")
    _run_script(_THREE_SCAN_SCRIPT)


def test_concurrent_two_scan_no_deadlock_subprocess():
    """N concurrent two-scan queries in fresh process; TimeoutExpired means deadlock."""
    pytest.importorskip("batchcorder")
    _run_script(_CONCURRENT_SCRIPT, timeout=TIMEOUT_SECONDS * 2)


def test_two_scan_correct_results():
    """Two-scan query returns correct values; threading.Event timeout catches deadlock."""
    batchcorder = pytest.importorskip("batchcorder")
    import xorq_datafusion as xdf

    schema = pa.schema([("x", pa.int64())])
    cache = batchcorder.StreamCache(
        pa.RecordBatchReader.from_batches(
            schema,
            [pa.record_batch({"x": [i]}, schema=schema) for i in range(5)],
        )
    )
    ctx = xdf.SessionContext()
    ctx.register_record_batch_reader("t", cache)

    done = threading.Event()
    result_holder = {}

    def run():
        try:
            batches = ctx.sql(
                """
                WITH totals AS (SELECT sum(x) AS total FROM t),
                     counts AS (SELECT count(x) AS cnt FROM t)
                SELECT total, cnt FROM totals CROSS JOIN counts
                """
            ).collect()
            result_holder["batches"] = batches
        except Exception as exc:
            result_holder["error"] = exc
        finally:
            done.set()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    finished = done.wait(timeout=TIMEOUT_SECONDS)

    assert finished, "query timed out — likely deadlock"
    assert "error" not in result_holder, f"query raised: {result_holder['error']}"

    rb = result_holder["batches"][0]
    assert rb.column("total")[0].as_py() == 10
    assert rb.column("cnt")[0].as_py() == 5


def test_two_scan_via_execute_stream():
    """Two-scan query via execute_stream must not deadlock."""
    batchcorder = pytest.importorskip("batchcorder")
    import xorq_datafusion as xdf

    schema = pa.schema([("x", pa.int64())])
    cache = batchcorder.StreamCache(
        pa.RecordBatchReader.from_batches(
            schema,
            [pa.record_batch({"x": [i]}, schema=schema) for i in range(5)],
        )
    )
    ctx = xdf.SessionContext()
    ctx.register_record_batch_reader("t", cache)

    done = threading.Event()
    result_holder = {}

    def run():
        try:
            df = ctx.sql(
                """
                WITH totals AS (SELECT sum(x) AS total FROM t),
                     counts AS (SELECT count(x) AS cnt FROM t)
                SELECT total, cnt FROM totals CROSS JOIN counts
                """
            )
            result_holder["batches"] = [b.to_pyarrow() for b in df.execute_stream()]
        except Exception as exc:
            result_holder["error"] = exc
        finally:
            done.set()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    finished = done.wait(timeout=TIMEOUT_SECONDS)

    assert finished, "execute_stream two-scan timed out — likely deadlock"
    assert "error" not in result_holder, f"query raised: {result_holder['error']}"

    table = pa.Table.from_batches(result_holder["batches"])
    assert table.column("total")[0].as_py() == 10
    assert table.column("cnt")[0].as_py() == 5


def test_union_all_two_scan_no_deadlock():
    """UNION ALL forces two scans of the same StreamCache table."""
    batchcorder = pytest.importorskip("batchcorder")
    import xorq_datafusion as xdf

    schema = pa.schema([("x", pa.int64())])
    cache = batchcorder.StreamCache(
        pa.RecordBatchReader.from_batches(
            schema,
            [pa.record_batch({"x": [i]}, schema=schema) for i in range(5)],
        )
    )
    ctx = xdf.SessionContext()
    ctx.register_record_batch_reader("t", cache)

    done = threading.Event()
    result_holder = {}

    def run():
        try:
            batches = ctx.sql("SELECT x FROM t UNION ALL SELECT x FROM t").collect()
            result_holder["batches"] = batches
        except Exception as exc:
            result_holder["error"] = exc
        finally:
            done.set()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    finished = done.wait(timeout=TIMEOUT_SECONDS)

    assert finished, "UNION ALL two-scan timed out — likely deadlock"
    assert "error" not in result_holder, f"query raised: {result_holder['error']}"

    table = pa.Table.from_batches(result_holder["batches"])
    assert table.num_rows == 10
    assert sorted(table.column("x").to_pylist()) == sorted([0, 1, 2, 3, 4] * 2)


def test_three_scan_no_deadlock():
    """Three CTEs each scanning the same StreamCache table must not deadlock."""
    batchcorder = pytest.importorskip("batchcorder")
    import xorq_datafusion as xdf

    schema = pa.schema([("x", pa.int64())])
    cache = batchcorder.StreamCache(
        pa.RecordBatchReader.from_batches(
            schema,
            [pa.record_batch({"x": [i]}, schema=schema) for i in range(5)],
        )
    )
    ctx = xdf.SessionContext()
    ctx.register_record_batch_reader("t", cache)

    done = threading.Event()
    result_holder = {}

    def run():
        try:
            batches = ctx.sql(
                """
                WITH totals AS (SELECT sum(x) AS total FROM t),
                     counts AS (SELECT count(x) AS cnt FROM t),
                     maxes  AS (SELECT max(x) AS mx   FROM t)
                SELECT total, cnt, mx
                  FROM totals CROSS JOIN counts CROSS JOIN maxes
                """
            ).collect()
            result_holder["batches"] = batches
        except Exception as exc:
            result_holder["error"] = exc
        finally:
            done.set()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    finished = done.wait(timeout=TIMEOUT_SECONDS)

    assert finished, "three-scan query timed out — likely deadlock"
    assert "error" not in result_holder, f"query raised: {result_holder['error']}"

    rb = result_holder["batches"][0]
    assert rb.column("total")[0].as_py() == 10
    assert rb.column("cnt")[0].as_py() == 5
    assert rb.column("mx")[0].as_py() == 4


def test_concurrent_two_scan_queries_no_deadlock():
    """N threads each running a simultaneous two-scan query must not deadlock."""
    batchcorder = pytest.importorskip("batchcorder")
    import xorq_datafusion as xdf

    N = 4
    schema = pa.schema([("x", pa.int64())])
    barrier = threading.Barrier(N)

    def worker(_idx):
        cache = batchcorder.StreamCache(
            pa.RecordBatchReader.from_batches(
                schema,
                [pa.record_batch({"x": [i]}, schema=schema) for i in range(5)],
            )
        )
        ctx = xdf.SessionContext()
        ctx.register_record_batch_reader("t", cache)
        barrier.wait()
        return ctx.sql(
            """
            WITH totals AS (SELECT sum(x) AS total FROM t),
                 counts AS (SELECT count(x) AS cnt FROM t)
            SELECT total, cnt FROM totals CROSS JOIN counts
            """
        ).collect()

    with concurrent.futures.ThreadPoolExecutor(max_workers=N) as executor:
        futures = [executor.submit(worker, i) for i in range(N)]
        done_futs, pending = concurrent.futures.wait(futures, timeout=TIMEOUT_SECONDS)

    assert not pending, f"{len(pending)} concurrent queries timed out — likely deadlock"

    for fut in done_futs:
        rb = fut.result()[0]
        assert rb.column("total")[0].as_py() == 10
        assert rb.column("cnt")[0].as_py() == 5
