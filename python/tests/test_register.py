from abc import ABCMeta, abstractmethod

import ibis
import pyarrow as pa
import pytest


class AbstractTableProvider(metaclass=ABCMeta):
    @abstractmethod
    def schema(self):
        pass

    @abstractmethod
    def scan(self, filters=None):
        pass


class IbisTableProvider(AbstractTableProvider):
    def __init__(self, table):
        self.table = table

    def schema(self):
        return self.table.schema().to_pyarrow()

    def scan(self, filters=None):
        table = self.table
        if filters:
            table = self.table.filter(filters)
        backend = table._find_backend()
        return backend.to_pyarrow_batches(table)


def test_register_table_provider(ctx, data_dir):
    table = ibis.read_parquet(data_dir / "data.rownum.parquet")
    ctx.register_table_provider("data", IbisTableProvider(table))

    actual = ctx.sql("select * from data").to_pandas()

    assert ctx.table_exist("data")
    assert not actual.empty


_FAILING_SCHEMA = pa.schema([("a", pa.int64())])


class FailingReaderProvider(AbstractTableProvider):
    """scan() returns a reader that yields one batch and then raises."""

    def schema(self):
        return _FAILING_SCHEMA

    def scan(self, filters=None):
        def gen():
            yield pa.record_batch({"a": pa.array([1, 2], pa.int64())})
            raise RuntimeError("reader blew up")

        return pa.RecordBatchReader.from_batches(_FAILING_SCHEMA, gen())


@pytest.mark.parametrize("sql", ["select * from boom", "select a from boom"])
@pytest.mark.parametrize(
    "drive",
    [
        lambda frame: frame.collect(),
        lambda frame: list(frame.execute_stream()),
    ],
    ids=["collect", "stream"],
)
def test_register_table_provider_reader_error_is_not_swallowed(ctx, sql, drive):
    """A Python reader that raises mid-stream must fail the query.

    The reader error used to be swallowed as an end-of-stream, so the query
    silently returned only the batches read before the failure. Both the
    projected and unprojected plans must surface it instead of truncating.
    """
    ctx.register_table_provider("boom", FailingReaderProvider())

    with pytest.raises(Exception, match="reader blew up"):
        drive(ctx.sql(sql))


def test_register_csv_multiple_paths(ctx, data_dir):
    fname = "iris.csv"
    table_name = "iris"
    iris_path = str(data_dir / fname)
    ctx.register_csv(table_name, [iris_path])
    ctx.register_csv(
        f"{table_name}_multiple_paths",
        [
            iris_path,
            iris_path,
        ],
    )
    table = ctx.table(table_name)
    table_multiple_paths = ctx.table(f"{table_name}_multiple_paths")

    assert any(f"{table_name}_multiple_paths" in t for t in ctx.tables())
    assert table.schema() == table_multiple_paths.schema()
    assert table_multiple_paths.count() == 2 * table.count()


def test_register_parquet_multiple_paths(ctx, data_dir):
    fname = "batting.parquet"
    table_name = "batting"
    batting_path = str(data_dir / fname)
    ctx.register_parquet(table_name, [batting_path])
    ctx.register_parquet(
        f"{table_name}_multiple_paths",
        [
            batting_path,
            batting_path,
        ],
    )
    table = ctx.table(table_name)
    table_multiple_paths = ctx.table(f"{table_name}_multiple_paths")

    assert any(f"{table_name}_multiple_paths" in t for t in ctx.tables())
    assert table_multiple_paths.count() == 2 * table.count()
