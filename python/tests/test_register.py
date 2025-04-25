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
