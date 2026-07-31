"""Property-based tests for execute_stream equivalence across UDF/UDAF return types.

Core property: execute_stream and collect produce the same concatenated data
for all supported Arrow return types, including binary variants.
"""

import subprocess
import sys
import textwrap
import threading
import time

import pyarrow as pa
import pytest
from hypothesis import HealthCheck, given, settings

import xorq_datafusion as xdf
from tests.strategies import udaf_dataframe, udf_dataframe


def collect_all(df) -> pa.Table:
    batches = df.collect()
    return pa.Table.from_batches(batches) if batches else pa.table({})


def stream_all(df) -> pa.Table:
    batches = [b.to_pyarrow() for b in df.execute_stream()]
    return pa.Table.from_batches(batches) if batches else pa.table({})


def stream_via_struct(df) -> pa.Table:
    """Reproduce the xorq/letsql struct-cast pipeline that triggered the bug."""
    pyarrow_schema = df.schema()
    struct_schema = pa.struct(pyarrow_schema)
    batches = [
        pa.RecordBatch.from_struct_array(
            pa.RecordBatch.from_arrays(
                batch.to_pyarrow().columns, schema=pyarrow_schema
            )
            .to_struct_array()
            .cast(struct_schema)
        )
        for batch in df.execute_stream()
    ]
    return pa.Table.from_batches(batches) if batches else pa.table({})


@given(udf_dataframe())
@settings(
    max_examples=50,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_udf_stream_matches_collect(ctx_df_type):
    _ctx, df, _rt = ctx_df_type
    via_collect = collect_all(df)
    # DataFusion re-executes lazily; same df object can be consumed twice.
    via_stream = stream_all(df)
    assert via_stream.num_rows > 0, (
        "stream returned no rows — df may have been consumed"
    )
    assert via_collect.equals(via_stream)


@given(udf_dataframe())
@settings(
    max_examples=50,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_udf_struct_pipeline_does_not_raise(ctx_df_type):
    """The struct-cast path must not raise C Data interface errors."""
    _ctx, df, _rt = ctx_df_type
    expected = collect_all(df)
    via_struct = stream_via_struct(df)
    assert via_struct.num_rows == expected.num_rows


@given(udf_dataframe())
@settings(
    max_examples=30,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_udf_result_column_type_matches_schema(ctx_df_type):
    """Column type in streamed batches matches declared schema."""
    _ctx, df, return_type = ctx_df_type
    declared = df.schema().field("result").type
    for batch in df.execute_stream():
        pa_batch = batch.to_pyarrow()
        assert pa_batch.schema.field("result").type == declared


@given(udaf_dataframe())
@settings(
    max_examples=50,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_udaf_stream_matches_collect(ctx_df_type):
    _ctx, df, _rt = ctx_df_type
    via_collect = collect_all(df)
    via_stream = stream_all(df)
    assert via_collect.equals(via_stream)


@given(udaf_dataframe())
@settings(
    max_examples=50,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_udaf_struct_pipeline_does_not_raise(ctx_df_type):
    """The struct-cast path must not raise C Data interface errors."""
    _ctx, df, _rt = ctx_df_type
    expected = collect_all(df)
    via_struct = stream_via_struct(df)
    assert via_struct.num_rows == expected.num_rows


@given(udaf_dataframe())
@settings(
    max_examples=30,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_udaf_aggregate_returns_one_row(ctx_df_type):
    """UDAF without GROUP BY always returns exactly one row."""
    _ctx, df, _rt = ctx_df_type
    via_stream = stream_all(df)
    assert via_stream.num_rows == 1


# A provider-backed stream (register_record_batch_reader) is driven by a
# spawn_blocking producer feeding a bounded channel. If that producer parked in
# blocking_send for the stream's whole lifetime, each partially-consumed-but-alive
# stream would pin one tokio blocking-pool thread; holding more than the pool cap
# (512) would exhaust it and hang the next query. The reserve()/per-batch design
# must instead park the coordinator as a cheap async task holding no thread.
_ABANDONED_STREAMS_SCRIPT = textwrap.dedent("""\
    import pyarrow as pa
    import xorq_datafusion as xdf

    schema = pa.schema([("x", pa.int64())])
    # 20 source batches (> channel capacity 8) so a lifetime producer would block.
    batches = [
        pa.record_batch(
            {"x": pa.array(range(i * 2000, (i + 1) * 2000), type=pa.int64())},
            schema=schema,
        )
        for i in range(20)
    ]
    tbl = pa.Table.from_batches(batches)   # re-scannable: __arrow_c_stream__ per scan
    ctx = xdf.SessionContext()
    ctx.register_record_batch_reader("t", tbl)

    # Hold far more partially-consumed streams than the blocking-pool cap (512).
    held = []
    for _ in range(600):
        s = ctx.sql("SELECT * FROM t").execute_stream()
        next(iter(s))            # start the producer + consume one batch, then abandon
        held.append(s)
    print("OK", len(held))
""")


def test_abandoned_streams_do_not_exhaust_blocking_pool():
    """Holding >512 partially-consumed provider-backed execute_stream results must
    not exhaust the tokio blocking pool. TimeoutExpired => the exhaustion hang."""
    proc = subprocess.run(
        [sys.executable, "-c", _ABANDONED_STREAMS_SCRIPT],
        timeout=30,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    assert proc.stdout.strip() == "OK 600", proc.stdout


# A pull is a blocking call into Python that cannot be interrupted, so a batch
# the query never asked for can strand a blocking-pool thread forever. Pulling
# only on demand (the AbstractTableProvider path) keeps that from happening at
# all; the register_record_batch_reader path keeps its read-ahead but draws on a
# bounded speculation budget, so the leak stops instead of exhausting the pool.
_BLOCKED_READ_AHEAD_SCRIPT = textwrap.dedent("""\
    import sys
    import threading

    import pyarrow as pa
    import xorq_datafusion as xdf

    mode = sys.argv[1]
    schema = pa.schema([("a", pa.int64())])
    forever = threading.Event()          # never set

    def reader():
        def gen():
            yield pa.record_batch({"a": pa.array([1], type=pa.int64())}, schema=schema)
            forever.wait()               # a batch beyond the LIMIT: must not be pulled
        return pa.RecordBatchReader.from_batches(schema, gen())

    class Provider:
        def schema(self):
            return schema

        def scan(self, filters=None):
            return reader()

    ctx = xdf.SessionContext()
    # Well past the 512-thread blocking-pool cap: one leak per query would hang.
    for i in range(600):
        ctx.deregister_table("t")
        if mode == "provider":
            ctx.register_table_provider("t", Provider())
        else:
            ctx.register_record_batch_reader("t", reader())
        rows = ctx.sql("SELECT * FROM t LIMIT 1").collect()
        assert sum(b.num_rows for b in rows) == 1, i
    print("OK")
""")


@pytest.mark.parametrize("mode", ["provider", "reader"])
def test_blocked_read_ahead_does_not_exhaust_blocking_pool(mode):
    """A reader that blocks on the batch after the one a LIMIT needs must not cost
    a blocking-pool thread per query. TimeoutExpired => the exhaustion hang."""
    proc = subprocess.run(
        [sys.executable, "-c", _BLOCKED_READ_AHEAD_SCRIPT, mode],
        timeout=60,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    assert proc.stdout.strip() == "OK", proc.stdout


def _counting_provider(pulls):
    """AbstractTableProvider whose reader records every batch it produces."""

    schema = pa.schema([("a", pa.int64())])

    class CountingProvider:
        def schema(self):
            return schema

        def scan(self, filters=None):
            def gen():
                for i in range(1000):
                    pulls.append(i)
                    yield pa.record_batch(
                        {"a": pa.array([i], type=pa.int64())}, schema=schema
                    )

            return pa.RecordBatchReader.from_batches(schema, gen())

    return CountingProvider()


def test_provider_scan_pulls_only_what_is_consumed():
    """The AbstractTableProvider path is demand-driven: no batch is read that the
    query did not poll for, so a reader with side effects (a paginated source) is
    not asked for pages the query discards."""
    ctx = xdf.SessionContext()

    limited = []
    ctx.register_table_provider("limited", _counting_provider(limited))
    rows = ctx.sql("SELECT * FROM limited LIMIT 1").collect()
    assert sum(b.num_rows for b in rows) == 1
    assert len(limited) == 1, f"LIMIT 1 pulled {len(limited)} batches"

    abandoned = []
    ctx.register_table_provider("abandoned", _counting_provider(abandoned))
    stream = ctx.sql("SELECT * FROM abandoned").execute_stream()
    batch = next(iter(stream))
    assert batch.to_pyarrow().num_rows == 1
    deadline = time.monotonic() + 0.5
    while time.monotonic() < deadline:
        assert len(abandoned) == 1, f"read ahead {len(abandoned)} batches while idle"
        time.sleep(0.05)


def _thread_recording_provider(threads_per_stream):
    """Provider whose reader records the thread each batch is produced on."""

    schema = pa.schema([("a", pa.int64())])

    class RecordingProvider:
        def schema(self):
            return schema

        def scan(self, filters=None):
            seen = set()
            threads_per_stream.append(seen)

            def gen():
                for i in range(60):
                    seen.add(threading.get_ident())
                    yield pa.record_batch(
                        {"a": pa.array([i], type=pa.int64())}, schema=schema
                    )

            return pa.RecordBatchReader.from_batches(schema, gen())

    return RecordingProvider()


def test_reader_stays_on_one_thread_across_batches():
    """Every batch of a stream must be produced on the same thread.

    A reader created lazily on the first pull may be bound to that thread
    (`sqlite3` cursors, `threading.local()`), so resuming it elsewhere breaks it.
    Several streams run concurrently because that is what shuffles pulls across
    threads when the reader is not pinned.
    """
    threads_per_stream = []
    ctx = xdf.SessionContext()
    ctx.register_table_provider("t", _thread_recording_provider(threads_per_stream))

    def drain():
        rows = 0
        for batch in ctx.sql("SELECT * FROM t").execute_stream():
            rows += batch.to_pyarrow().num_rows
            time.sleep(0.001)  # keep rounds re-dispatching
        assert rows == 60, rows

    workers = [threading.Thread(target=drain) for _ in range(8)]
    for w in workers:
        w.start()
    for w in workers:
        w.join()

    assert len(threads_per_stream) == 8
    for seen in threads_per_stream:
        assert len(seen) == 1, f"reader moved across {len(seen)} threads"


def test_batch_not_matching_schema_fails_the_query():
    """A drifted batch must fail the query, not reach kernels that trust the
    declared types and panic (arrow's `as_primitive` on a string column)."""
    schema = pa.schema([("a", pa.int64())])

    class DriftingProvider:
        def schema(self):
            return schema

        def scan(self, filters=None):
            def gen():
                yield pa.record_batch({"a": pa.array([1, 2], type=pa.int64())})
                yield pa.record_batch({"a": pa.array(["x"], type=pa.string())})

            return pa.RecordBatchReader.from_batches(schema, gen())

    ctx = xdf.SessionContext()
    ctx.register_table_provider("drift", DriftingProvider())
    with pytest.raises(Exception, match="does not match the table schema"):
        ctx.sql("SELECT a, a + 1 AS b FROM drift").collect()
