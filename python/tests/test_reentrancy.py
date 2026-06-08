"""Regression tests for issue #37.

`SessionContext.sql(...)` raised `RuntimeError: Already borrowed` when a second
`sql()`/DDL call re-entered the context while an earlier call from the same
context was still in flight. PySessionContext methods took `&mut self`, so PyO3
took an exclusive borrow held across the GIL-releasing `wait_for_future`; a
concurrent (or re-entrant teardown) `sql()` failed the borrow check.

The methods only need shared access (`SessionContext` is internally
Arc-shared), so they now take `&self` — many shared borrows may overlap.
"""

import concurrent.futures
import threading

import pyarrow as pa
import pytest

from xorq_datafusion import SessionContext, WindowEvaluator, udaf, udf, udwf

from tests.strategies import make_accumulator_class, make_udf_func


@pytest.fixture(scope="function")
def ctx_with_table():
    ctx = SessionContext()
    batch = pa.record_batch({"user_id": [1, 2, 3], "amount": [10.0, 20.0, 30.0]})
    ctx.register_record_batches("src", [[batch]])
    return ctx


def test_sql_reentrant_during_reader_teardown(ctx_with_table):
    """DROP VIEW issued from a reader's generator `finally` must not panic.

    Mirrors xorq's execution teardown: the result reader runs cleanup in its
    own generator's `finally`, which re-enters `ctx.sql(...)`.
    """
    ctx = ctx_with_table
    ctx.sql("CREATE VIEW v AS SELECT * FROM src").collect()

    df = ctx.sql("SELECT * FROM v LIMIT 1")
    schema = df.schema()

    def gen():
        try:
            for batch in df.execute_stream():
                yield batch.to_pyarrow().cast(schema)
        finally:
            # Re-enter the same context while the reader is still draining.
            ctx.sql("DROP VIEW v").collect()

    reader = pa.RecordBatchReader.from_batches(schema, gen())
    table = reader.read_all()
    assert table.num_rows == 1
    assert not ctx.table_exist("v")


def test_concurrent_sql_on_shared_context(ctx_with_table):
    """Many threads calling sql() on one shared context must not panic.

    Under load this is what made the latent `&mut self` borrow deterministic:
    one thread holds the borrow across `wait_for_future` (GIL released) while
    another re-borrows.
    """
    ctx = ctx_with_table
    errors = []
    barrier = threading.Barrier(8)

    def worker(i):
        try:
            barrier.wait()
            for _ in range(25):
                ctx.sql(
                    "SELECT user_id, sum(amount) FROM src GROUP BY user_id"
                ).collect()
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"sql() raised under concurrency: {errors}"


# ---------------------------------------------------------------------------
# Every method the fix changed from `&mut self` to `&self` must tolerate being
# called while another borrow on the same context is live. The hazard only
# arises for borrows held across the GIL-releasing `wait_for_future`, so each
# method is exercised concurrently with background threads spinning `sql()`
# (the borrow holder). Before the fix this raised `Already borrowed`.
# ---------------------------------------------------------------------------

_BATCH = pa.record_batch({"x": pa.array([1, 2, 3], type=pa.float64())})


class _NoopWindow(WindowEvaluator):
    def evaluate_all(self, values, num_rows):
        return pa.array([0.0] * num_rows)


def _invoke_register_record_batches(ctx, name):
    ctx.register_record_batches(name, [[_BATCH]])


def _invoke_register_record_batch_reader(ctx, name):
    reader = pa.RecordBatchReader.from_batches(_BATCH.schema, [_BATCH])
    ctx.register_record_batch_reader(name, reader)


def _invoke_register_dataframe(ctx, name):
    ctx.register_dataframe(name, ctx.sql("SELECT 1 AS a"))


def _invoke_register_udf(ctx, name):
    ctx.register_udf(
        udf(
            make_udf_func(pa.float64()),
            input_types=[pa.float64()],
            return_type=pa.float64(),
            volatility="volatile",
            name=name,
        )
    )


def _invoke_register_udaf(ctx, name):
    ctx.register_udaf(
        udaf(
            make_accumulator_class(pa.float64()),
            [pa.float64()],
            pa.float64(),
            [pa.binary()],
            volatility="volatile",
            name=name,
        )
    )


def _invoke_register_udwf(ctx, name):
    ctx.register_udwf(
        udwf(
            _NoopWindow(),
            [pa.float64()],
            pa.float64(),
            volatility="immutable",
            name=name,
        )
    )


def _invoke_deregister_table(ctx, name):
    ctx.register_record_batches(name, [[_BATCH]])
    ctx.deregister_table(name)


def _invoke_table(ctx, name):
    # `table` itself releases the GIL via wait_for_future — two of these
    # overlapping would have collided under `&mut self`.
    ctx.table("base")


_MODIFIED_METHODS = {
    "register_record_batches": _invoke_register_record_batches,
    "register_record_batch_reader": _invoke_register_record_batch_reader,
    "register_dataframe": _invoke_register_dataframe,
    "register_udf": _invoke_register_udf,
    "register_udaf": _invoke_register_udaf,
    "register_udwf": _invoke_register_udwf,
    "deregister_table": _invoke_deregister_table,
    "table": _invoke_table,
}


@pytest.mark.parametrize(
    "invoke", _MODIFIED_METHODS.values(), ids=list(_MODIFIED_METHODS)
)
def test_modified_method_concurrent_with_live_sql(invoke):
    """A now-`&self` method called from many threads while sql() runs on the
    same shared context must not raise `Already borrowed`."""
    ctx = SessionContext()
    ctx.register_record_batches("base", [[_BATCH]])

    errors = []
    stop = threading.Event()

    def spin():
        try:
            while not stop.is_set():
                ctx.sql("SELECT sum(x) FROM base").collect()
        except Exception as e:  # noqa: BLE001
            errors.append(("sql", e))

    spinners = [threading.Thread(target=spin, daemon=True) for _ in range(3)]
    for t in spinners:
        t.start()

    def hammer(tid):
        try:
            for i in range(20):
                invoke(ctx, f"m_{tid}_{i}")
        except Exception as e:  # noqa: BLE001
            errors.append(("method", e))

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
            futs = [ex.submit(hammer, t) for t in range(4)]
            for f in futs:
                f.result()
    finally:
        stop.set()
        for t in spinners:
            t.join(timeout=5)

    assert not errors, f"raised under concurrency: {errors}"
