import subprocess
import sys
import textwrap

import pytest

import xorq_datafusion as xdf


def _run(script, timeout=10):
    proc = subprocess.Popen(
        [sys.executable, "-c", textwrap.dedent(script)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        out, err = proc.communicate(timeout=timeout)
        return proc.returncode, out.decode(), err.decode()
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        pytest.fail("process hung — possible deadlock")


def test_close_is_exported():
    assert callable(xdf.close)
    assert "close" in xdf.__all__


def test_atexit_registered():
    code, out, err = _run("""
        import atexit
        before = atexit._ncallbacks()
        import xorq_datafusion  # noqa: F401
        after = atexit._ncallbacks()
        print("registered" if after > before else "not_registered")
    """)
    assert code == 0, err
    assert "registered" in out


def test_close_idempotent():
    code, out, err = _run("""
        import xorq_datafusion as xdf
        xdf.close()
        xdf.close(0)
        xdf.close(5)
        xdf.close()
        print("ok")
    """)
    assert code == 0, err
    assert "ok" in out


def test_close_after_query():
    code, out, err = _run("""
        import xorq_datafusion as xdf
        import pyarrow as pa
        ctx = xdf.SessionContext()
        batch = pa.RecordBatch.from_arrays([pa.array([1, 2, 3])], names=["a"])
        ctx.register_record_batches("t", [[batch]])
        fn = xdf.udf(lambda x: x.is_null(), [pa.int64()], pa.bool_(), "immutable", "fn")
        ctx.register_udf(fn)
        ctx.sql("select fn(a) from t").collect()
        xdf.close(0)
        print("ok")
    """)
    assert code == 0, err
    assert "ok" in out


def test_atexit_fires_cleanly():
    """atexit-registered close() must not raise on normal process exit."""
    code, out, err = _run("""
        import xorq_datafusion as xdf
        import pyarrow as pa
        ctx = xdf.SessionContext()
        batch = pa.RecordBatch.from_arrays([pa.array([1, 2, 3])], names=["a"])
        ctx.register_record_batches("t", [[batch]])
        fn = xdf.udf(lambda x: x.is_null(), [pa.int64()], pa.bool_(), "immutable", "fn")
        ctx.register_udf(fn)
        ctx.sql("select fn(a) from t").collect()
        print("ok")
        # atexit fires close() here — must not raise
    """)
    assert code == 0, err
    assert "ok" in out


def test_operations_after_close_raise():
    """After close(), DataFusion operations must raise, not hang."""
    code, out, err = _run("""
        import xorq_datafusion as xdf
        import pyarrow as pa
        ctx = xdf.SessionContext()
        batch = pa.RecordBatch.from_arrays([pa.array([1])], names=["a"])
        ctx.register_record_batches("t", [[batch]])
        xdf.close(0)
        try:
            ctx.sql("select a from t").collect()
            print("no_error")
        except BaseException:
            print("raised")
    """)
    assert code == 0, err
    assert "raised" in out
    assert "no_error" not in out


# A LIMIT stops consuming while the read-ahead pull thread is still inside the
# reader's generator (here, in time.sleep, GIL released). Nothing joins that
# thread before Py_Finalize; when it took the GIL back on the finalizing
# interpreter, CPython 3.13 pthread_exit'ed it and pyarrow's GIL guard aborted
# the process ("PyGILState_Release: thread state ... must be current when
# releasing"). It did so on every run; the atexit close() must now wait it out.
_PARKED_PULL_AT_EXIT = """
    import time
    import pyarrow as pa
    import xorq_datafusion as xdf

    def gen():
        for i in range(100):
            if i > 0:
                time.sleep({delay})
            yield pa.record_batch({{"a": [i]}})

    ctx = xdf.SessionContext()
    ctx.register_record_batch_reader(
        "s", pa.RecordBatchReader.from_batches(pa.schema({{"a": pa.int64()}}), gen())
    )
    print(ctx.sql("select * from s limit 2").to_arrow_table().num_rows)
"""


@pytest.mark.parametrize("attempt", range(3))
def test_exit_with_read_ahead_pull_inside_python(attempt):
    code, out, err = _run(_PARKED_PULL_AT_EXIT.format(delay=0.005))
    assert code == 0, err
    assert out.strip() == "2"
    assert "Fatal Python error" not in err


def test_close_reports_pull_still_inside_python():
    """A pull that outlives pull_timeout_secs is reported, not waited on forever."""
    code, out, err = _run(
        _PARKED_PULL_AT_EXIT.format(delay=3)
        + """
    import os, sys
    print(xdf.close(pull_timeout_secs=0.2))
    sys.stdout.flush()
    os._exit(0)  # the stuck pull would still crash a normal finalization
"""
    )
    assert code == 0, err
    assert out.split() == ["2", "False"]


def test_close_returns_true_when_pulls_finish():
    code, out, err = _run(
        _PARKED_PULL_AT_EXIT.format(delay=0.05)
        + """
    print(xdf.close())
"""
    )
    assert code == 0, err
    assert out.split() == ["2", "True"]


@pytest.mark.parametrize(
    ("pull_timeout_secs", "waited"),
    [('float("inf")', True), ('float("nan")', False), ("-1.0", False), ("None", False)],
)
def test_close_accepts_any_pull_timeout(pull_timeout_secs, waited):
    """inf waits without limit; NaN, negatives and None do not wait; none panic."""
    # The read-ahead pull sleeps 0.5s after the query returns: only a close() that
    # waits sees it finish. The atexit close() then waits out the rest.
    code, out, err = _run(
        _PARKED_PULL_AT_EXIT.format(delay=0.5)
        + f"""
    print(xdf.close(pull_timeout_secs={pull_timeout_secs}))
"""
    )
    assert code == 0, err
    assert out.split() == ["2", str(waited)]


# A Python UDF still running on a tokio worker when the interpreter exits. The
# worker is not a Python thread, so nothing joins it before Py_Finalize; its
# next GIL acquisition on the finalizing interpreter crashes (3.13) or hangs
# (3.14) the process. UDF calls now go through the same gate as the pulls.
_UDF_RUNNING_AT_EXIT = """
    import threading, time
    import pyarrow as pa
    import pyarrow.compute as pc
    import xorq_datafusion as xdf

    entered = threading.Event()

    def slow_plus_one(a):
        entered.set()
        time.sleep({delay})
        return pc.add(a, 1)

    ctx = xdf.SessionContext(
        config=xdf.SessionConfig().with_target_partitions(2).with_batch_size(8)
    )
    ctx.register_record_batches(
        "t", [[pa.record_batch({{"a": list(range(i, i + 8))}}) for i in range(0, 400, 8)]]
    )
    ctx.register_udf(
        xdf.udf(slow_plus_one, [pa.int64()], pa.int64(), "immutable", "slow_plus_one")
    )
    outcome = []

    def query():
        try:
            ctx.sql("select slow_plus_one(a) from t").collect()
            outcome.append("finished")
        except Exception as e:
            outcome.append(str(e))

    threading.Thread(target=query, daemon=True).start()
    entered.wait()
"""


@pytest.mark.parametrize("attempt", range(3))
def test_exit_with_python_udf_running(attempt):
    code, out, err = _run(_UDF_RUNNING_AT_EXIT.format(delay=0.01))
    assert code == 0, err
    assert "Fatal Python error" not in err


def test_close_waits_for_a_running_udf():
    """close() counts a UDF call already inside Python like a pull: it waits for
    it to return (here ~0.3s) before shutting the runtime down. Afterwards the
    query fails, either because its next UDF call is refused or because the
    runtime cancelled it first; it never finishes."""
    code, out, err = _run(
        _UDF_RUNNING_AT_EXIT.format(delay=0.3)
        + """
    start = time.monotonic()
    closed = xdf.close(pull_timeout_secs=5)
    print(closed, round(time.monotonic() - start, 2))
    deadline = time.monotonic() + 5
    while not outcome and time.monotonic() < deadline:
        time.sleep(0.01)
    print(outcome)
"""
    )
    assert code == 0, err
    first, outcome = out.strip().splitlines()
    closed, waited = first.split()
    assert closed == "True"
    assert float(waited) >= 0.1
    assert outcome != "[]"
    assert "finished" not in outcome
    assert "no longer calls into Python" in outcome or "cancelled" in outcome, outcome
