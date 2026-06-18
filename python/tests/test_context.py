from urllib.request import Request, urlopen
from uuid import uuid4

import pyarrow as pa
import pyarrow.dataset as ds
import pytest

from xorq_datafusion import (
    SessionConfig,
    SessionContext,
)


def test_create_context_no_args():
    SessionContext()


def test_create_context_session_config_only():
    SessionContext(config=SessionConfig())


def test_register_record_batches(ctx):
    # create a RecordBatch and register it as memtable
    batch = pa.RecordBatch.from_arrays(
        [pa.array([1, 2, 3]), pa.array([4, 5, 6])],
        names=["a", "b"],
    )

    ctx.register_record_batches("t", [[batch]])

    assert ctx.catalog().database().names() == {"t"}

    result = ctx.sql("SELECT a+b, a-b FROM t").collect()

    assert result[0].column(0) == pa.array([5, 7, 9])
    assert result[0].column(1) == pa.array([-3, -3, -3])


def test_register_record_batch_reader(ctx):
    batch = pa.RecordBatch.from_arrays(
        [pa.array([1, 2, 3]), pa.array([4, 5, 6])],
        names=["a", "b"],
    )

    reader = pa.RecordBatchReader.from_batches(batch.schema, [batch])

    ctx.register_record_batch_reader("t", reader)

    assert ctx.catalog().database().names() == {"t"}

    result = ctx.sql("SELECT a+b, a-b FROM t").collect()

    assert result[0].column(0) == pa.array([5, 7, 9])
    assert result[0].column(1) == pa.array([-3, -3, -3])


def test_register_record_batch_reader_replay(ctx):
    """A pa.Table supports multiple __arrow_c_stream__() calls, so the same
    registered table should be scannable across successive queries."""
    table = pa.table({"a": [1, 2, 3], "b": [4, 5, 6]})

    ctx.register_record_batch_reader("t", table)

    expected_sum = pa.array([5, 7, 9])
    expected_diff = pa.array([-3, -3, -3])

    for _ in range(3):
        result = ctx.sql("SELECT a+b, a-b FROM t").collect()
        assert result[0].column(0) == expected_sum
        assert result[0].column(1) == expected_diff


def test_register_record_batch_reader_lazy(ctx):
    """Batches must be fetched on demand.

    With LIMIT 1 against 10 batches of 100 rows each, a lazy implementation
    stops after reading the first batch.  An eager implementation would read
    all 10 batches before returning any results.
    """
    num_batches = 10
    rows_per_batch = 100
    schema = pa.schema([("x", pa.int64())])
    batches_fetched = []

    class TrackingReader:
        """Arrow-stream-compatible object that records each batch as it is pulled."""

        @property
        def schema(self):
            return schema

        def __arrow_c_stream__(self, requested_schema=None):
            def gen():
                for i in range(num_batches):
                    batches_fetched.append(i)
                    yield pa.record_batch(
                        {"x": list(range(rows_per_batch))}, schema=schema
                    )

            return pa.RecordBatchReader.from_batches(schema, gen()).__arrow_c_stream__(
                requested_schema
            )

    ctx.register_record_batch_reader("tracking_t", TrackingReader())

    result = ctx.sql("SELECT x FROM tracking_t LIMIT 1").collect()

    assert sum(len(b) for b in result) == 1
    # Laziness: LIMIT 1 with 100 rows/batch means only the first batch is needed.
    # Allow for one extra batch in case a prefetch is in flight when the limit fires.
    assert len(batches_fetched) < num_batches, (
        f"Expected lazy reading to stop early, "
        f"but {len(batches_fetched)}/{num_batches} batches were fetched"
    )


def test_register_record_batch_reader_batchcorder_self_join(ctx):
    """StreamCache wraps a single-use RecordBatchReader so it becomes replayable.

    A self-join requires two independent scans of the same registered table.
    Without replay capability the second scan would return empty results or
    raise an error.  batchcorder.StreamCache + .cast() gives us a
    CastingStreamCache whose __arrow_c_stream__ produces a fresh reader on
    every call, satisfying DataFusion's multi-scan requirement.
    """
    batchcorder = pytest.importorskip("batchcorder")

    schema = pa.schema([("id", pa.int64()), ("val", pa.float64())])
    batches = [
        pa.record_batch({"id": [1, 2, 3], "val": [0.5, 1.0, 1.5]}, schema=schema),
        pa.record_batch({"id": [4, 5], "val": [2.0, 2.5]}, schema=schema),
    ]
    # pa.RecordBatchReader is single-use; StreamCache makes it replayable.
    reader = pa.RecordBatchReader.from_batches(schema, batches)
    cache = batchcorder.StreamCache(reader)
    # CastingStreamCache.__arrow_c_stream__ returns a fresh reader each call.
    replayable = cache.cast(schema)

    ctx.register_record_batch_reader("t", replayable)

    # Self-join requires two scans; filter is pushed into the left side only.
    result = ctx.sql(
        """
        SELECT l.id, l.val, r.val AS r_val
          FROM t AS l
          JOIN t AS r ON l.id = r.id
         WHERE l.val > 0.5
         ORDER BY l.id
        """
    ).collect()

    assert len(result) == 1
    combined = result[0]
    assert combined.column("id") == pa.array([2, 3, 4, 5], type=pa.int64())
    assert combined.column("val") == pa.array([1.0, 1.5, 2.0, 2.5], type=pa.float64())
    assert combined.column("r_val") == pa.array([1.0, 1.5, 2.0, 2.5], type=pa.float64())

    # Ingest all remaining batches and confirm the cache is fully populated.
    # cache.ingest_all()
    assert cache.upstream_exhausted


def test_register_table(ctx, data_dir):
    ctx.register_csv("iris", [str(data_dir / "iris.csv")])

    default = ctx.catalog()
    public = default.database("public")
    assert public.names() == {"iris"}

    table = public.table("iris")
    ctx.register_table("iris_v2", table)
    assert public.table("iris_v2") is not None
    assert public.names() == {"iris", "iris_v2"}


def test_deregister_table(ctx, data_dir):
    ctx.register_csv("iris", [str(data_dir / "iris.csv")])

    default = ctx.catalog()
    public = default.database("public")
    assert public.names() == {"iris"}

    ctx.deregister_table("iris")
    assert not public.names()


def test_register_dataset(ctx):
    # create a RecordBatch and register it as a pyarrow.dataset.Dataset
    batch = pa.RecordBatch.from_arrays(
        [pa.array([1, 2, 3]), pa.array([4, 5, 6])],
        names=["a", "b"],
    )
    dataset = ds.dataset([batch])
    ctx.register_dataset("t", dataset)

    assert ctx.catalog().database().names() == {"t"}

    result = ctx.sql("SELECT a+b, a-b FROM t").collect()

    assert result[0].column(0) == pa.array([5, 7, 9])
    assert result[0].column(1) == pa.array([-3, -3, -3])


def test_dataset_filter(ctx, capfd):
    # create a RecordBatch and register it as a pyarrow.dataset.Dataset
    batch = pa.RecordBatch.from_arrays(
        [pa.array([1, 2, 3]), pa.array([4, 5, 6])],
        names=["a", "b"],
    )
    dataset = ds.dataset([batch])
    ctx.register_dataset("t", dataset)

    assert ctx.catalog().database().names() == {"t"}
    df = ctx.sql("SELECT a+b, a-b FROM t WHERE a BETWEEN 2 and 3 AND b > 5")

    # Make sure the filter was pushed down in Physical Plan
    df.explain()
    captured = capfd.readouterr()
    assert "filter_expr=(((a >= 2) and (a <= 3)) and (b > 5))" in captured.out

    result = df.collect()

    assert result[0].column(0) == pa.array([9])
    assert result[0].column(1) == pa.array([-3])


def test_dataset_count(ctx):
    # `datafusion-python` issue: https://github.com/apache/datafusion-python/issues/800
    batch = pa.RecordBatch.from_arrays(
        [pa.array([1, 2, 3]), pa.array([4, 5, 6])],
        names=["a", "b"],
    )
    dataset = ds.dataset([batch])
    ctx.register_dataset("t", dataset)

    # Testing the dataframe API
    df = ctx.table("t")
    assert df.count() == 3

    # Testing the SQL API
    count = ctx.sql("SELECT COUNT(*) FROM t")
    count = count.collect()
    assert count[0].column(0) == pa.array([3])


def test_pyarrow_predicate_pushdown_is_null(ctx, capfd):
    """Ensure that pyarrow filter gets pushed down for `IsNull`"""
    # create a RecordBatch and register it as a pyarrow.dataset.Dataset
    batch = pa.RecordBatch.from_arrays(
        [pa.array([1, 2, 3]), pa.array([4, 5, 6]), pa.array([7, None, 9])],
        names=["a", "b", "c"],
    )
    dataset = ds.dataset([batch])
    ctx.register_dataset("t", dataset)
    # Make sure the filter was pushed down in Physical Plan
    df = ctx.sql("SELECT a FROM t WHERE c is NULL")
    df.explain()
    captured = capfd.readouterr()
    assert "filter_expr=is_null(c, {nan_is_null=false})" in captured.out

    result = df.collect()
    assert result[0].column(0) == pa.array([2])


def test_table_exist(ctx):
    batch = pa.RecordBatch.from_arrays(
        [pa.array([1, 2, 3]), pa.array([4, 5, 6])],
        names=["a", "b"],
    )
    dataset = ds.dataset([batch])
    ctx.register_dataset("t", dataset)

    assert ctx.table_exist("t") is True


def test_table_not_found(ctx):
    with pytest.raises(ValueError, match="No table named"):
        ctx.table(f"not-found-{uuid4()}")


def test_register_csv(ctx, data_dir):
    ctx.register_csv("iris", [str(data_dir / "iris.csv")])
    assert ctx.sql("select * from iris") is not None


def test_register_parquet(ctx, data_dir):
    parquet_path = data_dir / "data.rownum.parquet"
    ctx.register_parquet("data", [str(parquet_path)])
    parquet_df = ctx.table("data")
    parquet_df.show()
    assert parquet_df is not None


def test_register_dataframe(ctx, data_dir):
    parquet_path = data_dir / "data.rownum.parquet"
    ctx.register_parquet("data", [str(parquet_path)])
    parquet_df = ctx.sql("select * from data where addr_state =  'GA' limit 20")

    ctx.register_dataframe("data_v2", parquet_df)

    assert ctx.table_exist("data_v2") is True
    df = ctx.table("data_v2").to_pandas()
    assert len(df) == 20


def test_get_object_metadata_local_filesystem(ctx, data_dir):
    url = data_dir / "data.rownum.parquet"
    metadata = ctx.get_object_metadata(str(url.resolve()), "parquet")

    assert isinstance(metadata, dict)


def test_large_batting_self_join_limit(ctx):
    """Self-join on a 16 000-row batting-like table with LIMIT 15 returns bounded results.

    Mirrors the batting self-join pattern from test_into_backend_datafusion but uses
    in-memory data so no external backend is required.
    """

    batchcorder = pytest.importorskip("batchcorder")

    n_rows = 16_000
    n_players = 1_000

    def cycle(seq, n):
        return [seq[i % len(seq)] for i in range(n)]

    table = pa.table(
        {
            "playerID": pa.array([f"player{i % n_players:04d}" for i in range(n_rows)]),
            "yearID": pa.array(cycle(list(range(1990, 2020)), n_rows), type=pa.int64()),
            "stint": pa.array([i % 3 + 1 for i in range(n_rows)], type=pa.int64()),
            "teamID": pa.array([f"TM{i % 30:02d}" for i in range(n_rows)]),
            "lgID": pa.array(["AL" if i % 2 == 0 else "NL" for i in range(n_rows)]),
            "G": pa.array([i % 162 + 1 for i in range(n_rows)], type=pa.int64()),
            "AB": pa.array([i % 600 for i in range(n_rows)], type=pa.int64()),
            "R": pa.array([i % 100 for i in range(n_rows)], type=pa.int64()),
            "H": pa.array([i % 200 for i in range(n_rows)], type=pa.int64()),
            "X2B": pa.array([i % 50 for i in range(n_rows)], type=pa.int64()),
            "X3B": pa.array([i % 20 for i in range(n_rows)], type=pa.int64()),
            "HR": pa.array([i % 50 for i in range(n_rows)], type=pa.int64()),
            "RBI": pa.array([i % 130 for i in range(n_rows)], type=pa.int64()),
            "SB": pa.array([i % 50 for i in range(n_rows)], type=pa.int64()),
            "CS": pa.array([i % 20 for i in range(n_rows)], type=pa.int64()),
            "BB": pa.array([i % 100 for i in range(n_rows)], type=pa.int64()),
            "SO": pa.array([i % 200 for i in range(n_rows)], type=pa.int64()),
            "IBB": pa.array([i % 30 for i in range(n_rows)], type=pa.int64()),
            "HBP": pa.array([i % 20 for i in range(n_rows)], type=pa.int64()),
            "SH": pa.array([i % 20 for i in range(n_rows)], type=pa.int64()),
            "SF": pa.array([i % 10 for i in range(n_rows)], type=pa.int64()),
            "GIDP": pa.array([i % 30 for i in range(n_rows)], type=pa.int64()),
        }
    )

    ctx.register_record_batch_reader(
        "ls_batting", batchcorder.StreamCache(table.to_reader(max_chunksize=1000))
    )

    result = ctx.sql(
        """
        SELECT
          t4.player_id,
          t4.year_id
        FROM (
          SELECT
            t1."playerID" AS player_id,
            t2."yearID" AS year_id
          FROM ls_batting AS t1
          INNER JOIN ls_batting AS t2
            ON t1."playerID" = t2."playerID"
          LIMIT 15
        ) AS t4
        """
    ).collect()

    total_rows = sum(len(b) for b in result)
    assert 0 < total_rows <= 15


def test_get_object_metadata_https(ctx):
    url = "https://raw.githubusercontent.com/ibis-project/testing-data/refs/heads/master/csv/astronauts.csv"

    metadata = ctx.get_object_metadata(url, "csv")
    assert isinstance(metadata, dict)

    request = Request(url, method="GET")
    with urlopen(request) as response:
        etag = response.headers.get("ETag")
        assert etag == metadata["e_tag"]
