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
