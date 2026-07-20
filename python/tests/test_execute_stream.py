"""Property-based tests for execute_stream equivalence across UDF/UDAF return types.

Core property: execute_stream and collect produce the same concatenated data
for all supported Arrow return types, including binary variants.
"""

import subprocess
import sys
import textwrap

import pyarrow as pa
from hypothesis import HealthCheck, given, settings

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
