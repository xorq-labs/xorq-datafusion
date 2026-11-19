"""Python UDF/UDAF/UDWF callbacks over a mutex-backed scan, under contention (#46).

The Python callbacks take the GIL on tokio workers, while the StreamCache
(batchcorder) scans hold its Rust mutex on pull threads. A deadlock needs a
cycle: a thread holding that mutex while it waits for the GIL, and a worker
holding the GIL while it waits for that mutex (or for runtime progress). These
tests combine both halves in one query, on both read paths, with several
threads and only two CPUs, so a cycle that is reachable through this crate
shows up as a hang.

Each case runs in a fresh subprocess: the worker pool is sized from the CPU
affinity when the runtime is first built, so affinity has to be narrowed
before ``xorq_datafusion`` is imported, and a hung process is killed by the
out-of-process timeout rather than by a watchdog that could itself be starved.
"""

import subprocess
import sys
import textwrap

import pytest

TIMEOUT_SECONDS = 30

_SCRIPT = textwrap.dedent("""\
    import os
    try:
        _a = sorted(os.sched_getaffinity(0))
        if len(_a) >= 2:
            os.sched_setaffinity(0, set(_a[:2]))
    except (AttributeError, OSError):
        pass

    import concurrent.futures
    import threading

    import pyarrow as pa
    import pyarrow.compute as pc
    import xorq_datafusion as xdf
    from batchcorder import StreamCache

    PATH = {path!r}
    N = 4
    ROWS = 20_000
    schema = pa.schema([("x", pa.int64()), ("k", pa.int64())])
    xs = list(range(ROWS))
    batches = [
        pa.record_batch(
            {{"x": xs[s:s + 512], "k": [v % 7 for v in xs[s:s + 512]]}}, schema=schema
        )
        for s in range(0, ROWS, 512)
    ]
    shared = StreamCache(pa.RecordBatchReader.from_batches(schema, batches))

    class Provider:
        def schema(self):
            return schema

        def scan(self, filters=None):
            return pa.RecordBatchReader.from_stream(shared.cast(schema))

    class Total(xdf.Accumulator):
        def __init__(self):
            self._sum = 0

        def state(self):
            return [pa.scalar(self._sum, pa.int64())]

        def update(self, values):
            self._sum += pc.sum(values).as_py() or 0

        def merge(self, states):
            # One array holding every partial state for this group.
            self._sum += pc.sum(states).as_py() or 0

        def evaluate(self):
            return pa.scalar(self._sum, pa.int64())

    class Ident(xdf.WindowEvaluator):
        def evaluate_all(self, values, num_rows):
            return values[0]

    plus_one = xdf.udf(
        lambda a: pc.add(a, 1), [pa.int64()], pa.int64(), "immutable", "plus_one"
    )
    total = xdf.udaf(Total, [pa.int64()], pa.int64(), [pa.int64()], "immutable", "total")
    ident = xdf.udwf(Ident(), [pa.int64()], pa.int64(), "immutable", "ident")

    ctx = xdf.SessionContext(
        config=xdf.SessionConfig().with_target_partitions(4).with_batch_size(1024)
    )
    if PATH == "reader":
        ctx.register_record_batch_reader("t", shared)
    else:
        ctx.register_table_provider("t", Provider())
    ctx.register_udf(plus_one)
    ctx.register_udaf(total)
    ctx.register_udwf(ident)

    # Two scans of the shared cache per query, a scalar UDF feeding a grouped UDAF
    # (repartitioned across 4 partitions), and a UDWF.
    QUERY = '''
        WITH g AS (SELECT k, total(plus_one(x)) AS s FROM t GROUP BY k),
             w AS (
                SELECT sum(v) AS ws
                FROM (SELECT ident(x) OVER (PARTITION BY k) AS v FROM t)
             )
        SELECT (SELECT sum(s) FROM g) AS gs, (SELECT ws FROM w) AS ws
    '''
    expected_gs = sum(xs) + ROWS
    expected_ws = sum(xs)

    barrier = threading.Barrier(N)

    def run(_):
        barrier.wait()
        out = []
        for _ in range(3):
            rb = ctx.sql(QUERY).collect()[0]
            out.append((rb.column("gs")[0].as_py(), rb.column("ws")[0].as_py()))
        return out

    with concurrent.futures.ThreadPoolExecutor(N) as pool:
        results = [r for rs in pool.map(run, range(N)) for r in rs]

    assert all(r == (expected_gs, expected_ws) for r in results), results
    print("OK")
""")


@pytest.mark.parametrize("path", ["reader", "provider"])
def test_python_callbacks_over_shared_cache_no_deadlock(path):
    """TimeoutExpired means a GIL<->mutex or GIL<->worker cycle; a wrong total
    means a shared-cache concurrency regression."""
    pytest.importorskip("batchcorder")
    proc = subprocess.run(
        [sys.executable, "-c", _SCRIPT.format(path=path)],
        timeout=TIMEOUT_SECONDS,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"stdout: {proc.stdout}\nstderr: {proc.stderr}"
    assert proc.stdout.strip() == "OK"
