from operator import methodcaller

import pytest


@pytest.fixture(scope="function")
def ctx_data(ctx, data_dir):
    ctx.register_parquet(
        "functional_alltypes", str(data_dir / "functional_alltypes.parquet")
    )
    ctx.register_parquet("batting", str(data_dir / "batting.parquet"))
    return ctx


def get_queries():
    from pathlib import Path

    queries_file_path = Path(__file__).parent / "fixtures" / "queries.sql"
    with open(queries_file_path) as queries_file:
        result = [query.strip() for query in queries_file]
    return result


queries = get_queries()


@pytest.mark.parametrize("query", queries)
@pytest.mark.parametrize(
    "collection", [methodcaller(method) for method in ("collect", "execute_stream")]
)
def test_sql_query(ctx_data, query, collection):
    df = ctx_data.sql(query)
    assert collection(df) is not None
