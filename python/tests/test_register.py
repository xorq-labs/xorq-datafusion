from abc import abstractmethod, ABCMeta


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
    import ibis

    table = ibis.read_parquet(data_dir / "data.rownum.parquet")
    ctx.register_table_provider("data", IbisTableProvider(table))

    actual = ctx.sql("select * from data").to_pandas()

    assert ctx.table_exist("data")
    assert not actual.empty


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
