import pytest


@pytest.fixture(scope="function")
def ctx_data(ctx, data_dir):
    ctx.register_parquet(
        "functional_alltypes", str(data_dir / "functional_alltypes.parquet")
    )
    ctx.register_parquet("batting", str(data_dir / "batting.parquet"))
    ctx.register_parquet("awards_players", str(data_dir / "awards_players.parquet"))
    return ctx


def get_queries():
    from pathlib import Path

    queries_file_path = Path(__file__).parent / "fixtures" / "queries.sql"
    with open(queries_file_path) as queries_file:
        result = [query.strip() for query in queries_file]
    return result


queries = get_queries()


@pytest.mark.parametrize("query", queries)
def test_sql_query(ctx_data, query):
    df = ctx_data.sql(query)
    assert df.collect() is not None


def to_pyarrow_batches(batches, schema):
    import pyarrow as pa

    def make_gen():
        return (batch.to_pyarrow().cast(schema) for batch in batches)

    return pa.RecordBatchReader.from_batches(schema, make_gen())


def to_pandas(batches, schema):
    batch_reader = to_pyarrow_batches(batches, schema)
    return batch_reader.read_pandas(timestamp_as_object=True)


def to_pyarrow(batches, schema):
    batch_reader = to_pyarrow_batches(batches, schema)
    return batch_reader.read_all()


@pytest.mark.parametrize("query", queries)
@pytest.mark.parametrize("method", [to_pyarrow_batches, to_pandas, to_pyarrow])
def test_sql_query_execute_stream(ctx_data, query, method):
    df = ctx_data.sql(query)
    assert method(df.execute_stream(), df.schema()) is not None


def test_tables(ctx_data):
    assert ctx_data.tables() == {"functional_alltypes", "batting", "awards_players"}
