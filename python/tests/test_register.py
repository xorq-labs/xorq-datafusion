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


class _RaisingSchemaProvider(AbstractTableProvider):
    """schema() raises; scan() is never reached."""

    def schema(self):
        raise RuntimeError("no schema for you")

    def scan(self, filters=None):
        raise AssertionError("scan must not be reached")


class _NotASchemaProvider(AbstractTableProvider):
    """schema() returns something that is not a pyarrow Schema."""

    def schema(self):
        return 42

    def scan(self, filters=None):
        raise AssertionError("scan must not be reached")


@pytest.mark.parametrize(
    ("provider", "match"),
    [
        (_RaisingSchemaProvider(), "no schema for you"),
        (_NotASchemaProvider(), "Schema"),
    ],
    ids=["raises", "wrong-type"],
)
def test_register_table_provider_bad_schema_fails_at_registration(ctx, provider, match):
    """A provider schema that cannot be read must fail the registration call.

    The schema is read once at registration rather than on every planner call,
    so a bad one surfaces here as a Python exception instead of panicking on
    whichever thread happens to be planning.
    """
    with pytest.raises(Exception, match=match):
        ctx.register_table_provider("bad", provider)

    assert not ctx.table_exist("bad")


def test_register_table_provider_reads_schema_once(ctx, data_dir):
    """The planner must not call back into `schema()` for every plan."""
    table = ibis.read_parquet(data_dir / "data.rownum.parquet")

    class CountingProvider(IbisTableProvider):
        def __init__(self, table):
            super().__init__(table)
            self.schema_calls = 0

        def schema(self):
            self.schema_calls += 1
            return super().schema()

    provider = CountingProvider(table)
    ctx.register_table_provider("counted", provider)
    assert provider.schema_calls == 1

    for _ in range(3):
        assert not ctx.sql("select * from counted").to_pandas().empty
    assert provider.schema_calls == 1


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
