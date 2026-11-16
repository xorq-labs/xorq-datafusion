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
    "pull_timeout_secs", ['float("inf")', 'float("nan")', "-1.0", "None"]
)
def test_close_accepts_any_pull_timeout(pull_timeout_secs):
    """inf waits without limit; NaN, negatives and None do not wait; none panic."""
    code, out, err = _run(
        _PARKED_PULL_AT_EXIT.format(delay=0.05)
        + f"""
    xdf.close(pull_timeout_secs={pull_timeout_secs})
    print("closed")
"""
    )
    assert code == 0, err
    assert out.split()[-1] == "closed"
