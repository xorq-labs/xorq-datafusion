"""Property-based tests for execute_stream equivalence across UDF/UDAF return types.

Core property: execute_stream and collect produce the same concatenated data
for all supported Arrow return types, including binary variants.
"""

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
