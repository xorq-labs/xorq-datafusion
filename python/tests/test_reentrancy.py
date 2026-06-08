"""Regression tests for issue #37.

`SessionContext.sql(...)` raised `RuntimeError: Already borrowed` when a second
`sql()`/DDL call re-entered the context while an earlier call from the same
context was still in flight. PySessionContext methods took `&mut self`, so PyO3
took an exclusive borrow held across the GIL-releasing `wait_for_future`; a
concurrent (or re-entrant teardown) `sql()` failed the borrow check.

The methods only need shared access (`SessionContext` is internally
Arc-shared), so they now take `&self` — many shared borrows may overlap.
"""

import threading

import pyarrow as pa
import pytest

from xorq_datafusion import SessionContext


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
