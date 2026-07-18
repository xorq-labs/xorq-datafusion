"""Regression and property-based tests: StreamCache multi-scan correctness and deadlock-freedom.

Root cause of the deadlock: PyRecordBatchProviderExec::execute() used to call Python::attach
(GIL acquisition) on a Tokio async worker thread. For two-scan queries, this
created a circular wait between async workers holding the GIL and
spawn_blocking threads holding batchcorder's DatasetInner mutex.

Fix: move all Python::attach calls into spawn_blocking so GIL acquisition
never happens on async worker threads.

In addition to the fixed-data regression tests, property-based tests cover the
same five multi-scan patterns with arbitrary data sized to exceed DataFusion's
default batch size (8192 rows) and a wide schema (int64 + float64 + utf8).
"""

import collections
import concurrent.futures
import subprocess
import sys
import textwrap
import threading

import pyarrow as pa
import pytest
from hypothesis import HealthCheck, example, given, settings
from hypothesis import strategies as st

import xorq_datafusion as xdf

TIMEOUT_SECONDS = 8
_HYPOTHESIS_TIMEOUT = 15
_SCHEMA = pa.schema([("x", pa.int64()), ("y", pa.float64()), ("s", pa.utf8())])

# DataFusion's default batch size; edge cases straddle this boundary.
_DF_BATCH = 8_192

# Guaranteed edge cases injected into every prop test via @_stream_cache_examples.
# Covers: empty, minimal, exact DataFusion boundary, boundary+1 (single and many
# StreamCache batches), and double-boundary.
_EDGE_CASES = [
    ([], 50),  # empty table
    ([0, 1], 50),  # 2 rows, single StreamCache batch
    ([0, 1] * (_DF_BATCH // 2), _DF_BATCH),  # exactly 1 DataFusion batch
    ([0, 1] * (_DF_BATCH // 2) + [0], _DF_BATCH + 1),  # boundary+1, 1 StreamCache batch
    (
        [0, 1] * (_DF_BATCH // 2) + [0],
        100,
    ),  # boundary+1, many small StreamCache batches
    ([0, 1] * _DF_BATCH, _DF_BATCH),  # exactly 2 DataFusion batches
]


def _stream_cache_examples(fn):
    """Apply all StreamCache edge-case @example decorators to a prop test."""
    for case in _EDGE_CASES:
        fn = example(values_and_batch_size=case)(fn)
    return fn


_DEADLOCK_SCRIPT = textwrap.dedent("""\
    import pyarrow as pa
    import xorq_datafusion as xdf
    from batchcorder import StreamCache

    schema = pa.schema([("x", pa.int64())])
    cache = StreamCache(
        pa.RecordBatchReader.from_batches(
            schema,
            (pa.record_batch({"x": [i]}, schema=schema) for i in range(5)),
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
    result_schema = df.schema()
    reader = pa.RecordBatchReader.from_batches(
        result_schema,
        (batch.to_pyarrow().cast(result_schema) for batch in df.execute_stream()),
    )
    table = reader.read_all()
    total = table.column("total")[0].as_py()
    cnt = table.column("cnt")[0].as_py()
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
        barrier.wait(timeout=8)
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


def test_two_scan_no_deadlock_subprocess():
    """Two-scan query completes within timeout; TimeoutExpired means deadlock."""
    pytest.importorskip("batchcorder")
    _run_script(_DEADLOCK_SCRIPT)


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
        barrier.wait(timeout=TIMEOUT_SECONDS)
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


# ---------------------------------------------------------------------------
# Property-based tests (hypothesis)
# ---------------------------------------------------------------------------


@st.composite
def _table_data(draw):
    """Return (values, batch_size) with varied row count and batch structure.

    `unique=True` + `min_size=2` guarantees at least 2 distinct values so
    max/min properties are non-trivial. `batch_size` floor of 50 prevents
    creating tens of thousands of single-row Arrow batches.
    """
    n_rows = draw(st.integers(min_value=0, max_value=20_000))
    base = draw(
        st.lists(
            st.integers(min_value=-1_000, max_value=1_000),
            min_size=2,
            max_size=100,
            unique=True,
        )
    )
    values = (base * (n_rows // len(base) + 1))[:n_rows]
    batch_size = draw(st.integers(min_value=50, max_value=5_000))
    return values, batch_size


def _make_stream_cache(values, batch_size):
    """StreamCache with int64/float64/utf8 columns split into batch_size-row batches."""
    # Lazy import keeps batchcorder optional (callers guard with importorskip).
    from batchcorder import StreamCache  # noqa: PLC0415

    def _batches():
        for start in range(0, len(values), batch_size):
            chunk = values[start : start + batch_size]
            yield pa.record_batch(
                {
                    "x": pa.array(chunk, type=pa.int64()),
                    "y": pa.array([float(v) * 0.001 for v in chunk], type=pa.float64()),
                    "s": pa.array([str(abs(v)) for v in chunk], type=pa.utf8()),
                },
                schema=_SCHEMA,
            )

    return StreamCache(pa.RecordBatchReader.from_batches(_SCHEMA, _batches()))


def _run_with_timeout(fn, timeout=_HYPOTHESIS_TIMEOUT):
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
        pytest.fail("query timed out — likely deadlock")
    if "error" in holder:
        raise holder["error"]
    return holder["result"]


@_stream_cache_examples
@given(_table_data())
@settings(max_examples=20, suppress_health_check=[HealthCheck.too_slow])
def test_prop_two_scan_cte_collect_correct_results(values_and_batch_size):
    """Four-scan CTE via collect returns correct aggregates for all three columns."""
    values, batch_size = values_and_batch_size
    pytest.importorskip("batchcorder")
    ctx = xdf.SessionContext()
    ctx.register_record_batch_reader("t", _make_stream_cache(values, batch_size))

    batches = _run_with_timeout(
        lambda: ctx.sql(
            """
            WITH totals   AS (SELECT sum(x)   AS total   FROM t),
                 counts   AS (SELECT count(x) AS cnt     FROM t),
                 y_totals AS (SELECT sum(y)   AS y_total FROM t),
                 s_counts AS (SELECT count(s) AS s_cnt   FROM t)
            SELECT total, cnt, y_total, s_cnt
              FROM totals CROSS JOIN counts
                          CROSS JOIN y_totals
                          CROSS JOIN s_counts
            """
        ).collect()
    )
    expected_x_sum = sum(values) if values else None
    expected_y_total = sum(float(v) * 0.001 for v in values) if values else None
    rb = batches[0]
    assert rb.column("total")[0].as_py() == expected_x_sum
    assert rb.column("cnt")[0].as_py() == len(values)
    if expected_y_total is None:
        assert rb.column("y_total")[0].as_py() is None
    else:
        assert rb.column("y_total")[0].as_py() == pytest.approx(
            expected_y_total, rel=1e-5, abs=1e-9
        )
    assert rb.column("s_cnt")[0].as_py() == len(values)


@_stream_cache_examples
@given(_table_data())
@settings(max_examples=20, suppress_health_check=[HealthCheck.too_slow])
def test_prop_two_scan_execute_stream_correct_results(values_and_batch_size):
    """Four-scan CTE via execute_stream returns correct aggregates for all three columns."""
    values, batch_size = values_and_batch_size
    pytest.importorskip("batchcorder")
    ctx = xdf.SessionContext()
    ctx.register_record_batch_reader("t", _make_stream_cache(values, batch_size))

    def run():
        df = ctx.sql(
            """
            WITH totals   AS (SELECT sum(x)   AS total   FROM t),
                 counts   AS (SELECT count(x) AS cnt     FROM t),
                 y_totals AS (SELECT sum(y)   AS y_total FROM t),
                 s_counts AS (SELECT count(s) AS s_cnt   FROM t)
            SELECT total, cnt, y_total, s_cnt
              FROM totals CROSS JOIN counts
                          CROSS JOIN y_totals
                          CROSS JOIN s_counts
            """
        )
        return [b.to_pyarrow() for b in df.execute_stream()]

    expected_x_sum = sum(values) if values else None
    expected_y_total = sum(float(v) * 0.001 for v in values) if values else None
    table = pa.Table.from_batches(_run_with_timeout(run))
    assert table.column("total")[0].as_py() == expected_x_sum
    assert table.column("cnt")[0].as_py() == len(values)
    if expected_y_total is None:
        assert table.column("y_total")[0].as_py() is None
    else:
        assert table.column("y_total")[0].as_py() == pytest.approx(
            expected_y_total, rel=1e-5, abs=1e-9
        )
    assert table.column("s_cnt")[0].as_py() == len(values)


@_stream_cache_examples
@given(_table_data())
@settings(max_examples=20, suppress_health_check=[HealthCheck.too_slow])
def test_prop_union_all_two_scan_correct_results(values_and_batch_size):
    """UNION ALL two-scan returns all columns from every row exactly twice."""
    values, batch_size = values_and_batch_size
    pytest.importorskip("batchcorder")
    ctx = xdf.SessionContext()
    ctx.register_record_batch_reader("t", _make_stream_cache(values, batch_size))

    batches = _run_with_timeout(
        lambda: ctx.sql(
            "SELECT x, y, s FROM t UNION ALL SELECT x, y, s FROM t"
        ).collect()
    )
    # schema required: empty input yields 0 batches and from_batches needs a hint
    table = pa.Table.from_batches(batches, schema=_SCHEMA)
    assert table.num_rows == 2 * len(values)
    assert collections.Counter(table.column("x").to_pylist()) == collections.Counter(
        values * 2
    )
    assert collections.Counter(table.column("s").to_pylist()) == collections.Counter(
        [str(abs(v)) for v in values] * 2
    )
    expected_y_sum = sum(float(v) * 0.001 for v in values) * 2
    assert sum(table.column("y").to_pylist()) == pytest.approx(
        expected_y_sum, rel=1e-5, abs=1e-9
    )


@_stream_cache_examples
@given(_table_data())
@settings(max_examples=20, suppress_health_check=[HealthCheck.too_slow])
def test_prop_three_scan_cte_correct_results(values_and_batch_size):
    """Five-scan CTE returns correct sum, count, max, and aggregates for all columns."""
    values, batch_size = values_and_batch_size
    pytest.importorskip("batchcorder")
    ctx = xdf.SessionContext()
    ctx.register_record_batch_reader("t", _make_stream_cache(values, batch_size))

    batches = _run_with_timeout(
        lambda: ctx.sql(
            """
            WITH totals   AS (SELECT sum(x)   AS total   FROM t),
                 counts   AS (SELECT count(x) AS cnt     FROM t),
                 maxes    AS (SELECT max(x)   AS mx      FROM t),
                 y_totals AS (SELECT sum(y)   AS y_total FROM t),
                 s_counts AS (SELECT count(s) AS s_cnt   FROM t)
            SELECT total, cnt, mx, y_total, s_cnt
              FROM totals CROSS JOIN counts CROSS JOIN maxes
                          CROSS JOIN y_totals CROSS JOIN s_counts
            """
        ).collect()
    )
    expected_x_sum = sum(values) if values else None
    expected_mx = max(values) if values else None
    expected_y_total = sum(float(v) * 0.001 for v in values) if values else None
    rb = batches[0]
    assert rb.column("total")[0].as_py() == expected_x_sum
    assert rb.column("cnt")[0].as_py() == len(values)
    assert rb.column("mx")[0].as_py() == expected_mx
    if expected_y_total is None:
        assert rb.column("y_total")[0].as_py() is None
    else:
        assert rb.column("y_total")[0].as_py() == pytest.approx(
            expected_y_total, rel=1e-5, abs=1e-9
        )
    assert rb.column("s_cnt")[0].as_py() == len(values)


@_stream_cache_examples
@given(_table_data())
@settings(
    max_examples=10,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_prop_concurrent_two_scan_correct_results(values_and_batch_size):
    """N concurrent two-scan queries each return correct sum and count."""
    values, batch_size = values_and_batch_size
    pytest.importorskip("batchcorder")

    N = 4
    barrier = threading.Barrier(N)
    expected_sum = sum(values) if values else None
    expected_cnt = len(values)
    expected_y_total = sum(float(v) * 0.001 for v in values) if values else None

    def worker(_idx):
        ctx = xdf.SessionContext()
        ctx.register_record_batch_reader("t", _make_stream_cache(values, batch_size))
        barrier.wait(timeout=_HYPOTHESIS_TIMEOUT)
        return ctx.sql(
            """
            WITH totals   AS (SELECT sum(x)   AS total   FROM t),
                 counts   AS (SELECT count(x) AS cnt     FROM t),
                 y_totals AS (SELECT sum(y)   AS y_total FROM t),
                 s_counts AS (SELECT count(s) AS s_cnt   FROM t)
            SELECT total, cnt, y_total, s_cnt
              FROM totals CROSS JOIN counts
                          CROSS JOIN y_totals
                          CROSS JOIN s_counts
            """
        ).collect()

    with concurrent.futures.ThreadPoolExecutor(max_workers=N) as executor:
        futures = [executor.submit(worker, i) for i in range(N)]
        done_futs, pending = concurrent.futures.wait(
            futures, timeout=_HYPOTHESIS_TIMEOUT * 2
        )

    assert not pending, f"{len(pending)} concurrent queries timed out — likely deadlock"

    for fut in done_futs:
        rb = fut.result()[0]
        assert rb.column("total")[0].as_py() == expected_sum
        assert rb.column("cnt")[0].as_py() == expected_cnt
        if expected_y_total is None:
            assert rb.column("y_total")[0].as_py() is None
        else:
            assert rb.column("y_total")[0].as_py() == pytest.approx(
                expected_y_total, rel=1e-5, abs=1e-9
            )
        assert rb.column("s_cnt")[0].as_py() == expected_cnt


@_stream_cache_examples
@given(_table_data())
@settings(
    max_examples=10,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_prop_concurrent_shared_cache_correct_results(values_and_batch_size):
    """N workers sharing one StreamCache instance each return correct results.

    Tests thread-safety of StreamCache's replay mechanism under concurrent
    readers, as opposed to N independent caches running in parallel.
    """
    values, batch_size = values_and_batch_size
    pytest.importorskip("batchcorder")
    N = 4
    barrier = threading.Barrier(N)
    shared_cache = _make_stream_cache(values, batch_size)
    expected_sum = sum(values) if values else None
    expected_cnt = len(values)
    expected_y_total = sum(float(v) * 0.001 for v in values) if values else None

    def worker(_idx):
        ctx = xdf.SessionContext()
        ctx.register_record_batch_reader("t", shared_cache)
        barrier.wait(timeout=_HYPOTHESIS_TIMEOUT)
        return ctx.sql(
            """
            WITH totals   AS (SELECT sum(x)   AS total   FROM t),
                 counts   AS (SELECT count(x) AS cnt     FROM t),
                 y_totals AS (SELECT sum(y)   AS y_total FROM t),
                 s_counts AS (SELECT count(s) AS s_cnt   FROM t)
            SELECT total, cnt, y_total, s_cnt
              FROM totals CROSS JOIN counts
                          CROSS JOIN y_totals
                          CROSS JOIN s_counts
            """
        ).collect()

    with concurrent.futures.ThreadPoolExecutor(max_workers=N) as executor:
        futures = [executor.submit(worker, i) for i in range(N)]
        done_futs, pending = concurrent.futures.wait(
            futures, timeout=_HYPOTHESIS_TIMEOUT * 2
        )

    assert not pending, (
        f"{len(pending)} shared-cache queries timed out — likely deadlock"
    )

    for fut in done_futs:
        rb = fut.result()[0]
        assert rb.column("total")[0].as_py() == expected_sum
        assert rb.column("cnt")[0].as_py() == expected_cnt
        if expected_y_total is None:
            assert rb.column("y_total")[0].as_py() is None
        else:
            assert rb.column("y_total")[0].as_py() == pytest.approx(
                expected_y_total, rel=1e-5, abs=1e-9
            )
        assert rb.column("s_cnt")[0].as_py() == expected_cnt
