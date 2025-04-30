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
    # create a RecordBatch and register it as memtable
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


def test_register_table(ctx, data_dir):
    ctx.register_csv("iris", str(data_dir / "iris.csv"))

    default = ctx.catalog()
    public = default.database("public")
    assert public.names() == {"iris"}

    table = public.table("iris")
    ctx.register_table("iris_v2", table)
    assert public.table("iris_v2") is not None
    assert public.names() == {"iris", "iris_v2"}


def test_deregister_table(ctx, data_dir):
    ctx.register_csv("iris", str(data_dir / "iris.csv"))

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
    from uuid import uuid4

    with pytest.raises(Exception):
        ctx.table(f"not-found-{uuid4()}")


def test_register_csv(ctx, data_dir):
    ctx.register_csv("iris", str(data_dir / "iris.csv"))
    assert ctx.sql("select * from iris") is not None


def test_register_parquet(ctx, data_dir):
    parquet_path = data_dir / "data.rownum.parquet"
    ctx.register_parquet("data", str(parquet_path))
    parquet_df = ctx.table("data")
    parquet_df.show()
    assert parquet_df is not None


def test_register_dataframe(ctx, data_dir):
    parquet_path = data_dir / "data.rownum.parquet"
    ctx.register_parquet("data", str(parquet_path))
    parquet_df = ctx.sql("select * from data where addr_state =  'GA' limit 20")

    ctx.register_dataframe("data_v2", parquet_df)

    assert ctx.table_exist("data_v2") is True
    df = ctx.table("data_v2").to_pandas()
    assert len(df) == 20


def test_get_object_metadata_local_filesystem(ctx, data_dir):
    url = data_dir / "data.rownum.parquet"
    metadata = ctx.get_object_metadata(str(url.resolve()), "parquet")

    assert isinstance(metadata, dict)


def test_get_object_metadata_https(ctx):
    from urllib.request import Request, urlopen

    url = "https://raw.githubusercontent.com/ibis-project/testing-data/refs/heads/master/csv/astronauts.csv"

    metadata = ctx.get_object_metadata(url, "csv")
    assert isinstance(metadata, dict)

    request = Request(url, method="GET")
    with urlopen(request) as response:
        etag = response.headers.get("ETag")
        assert etag == metadata["e_tag"]
