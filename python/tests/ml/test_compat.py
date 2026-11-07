import subprocess
import sys

import pyarrow as pa
import pytest

import xorq_datafusion.ml as ml
from xorq_datafusion import SessionConfig, SessionContext, _internal


def _run(code):
    return subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    ).stdout.strip()


def test_base_import_does_not_load_sklearn():
    out = _run(
        "import sys, xorq_datafusion; "
        "print('sklearn' in sys.modules, 'xorq_datafusion.ml' in sys.modules)"
    )
    assert out == "False False"


def test_ml_public_names():
    assert set(ml.__all__) == {
        "Model",
        "Reason",
        "Supported",
        "Unsupported",
        "compile",
        "fit",
        "supports",
    }


def test_native_ml_submodule_registered():
    assert hasattr(_internal, "ml")


COMPAT_QUERIES = [
    "SELECT * FROM batting LIMIT 5",
    'SELECT "playerID", "yearID", "HR" FROM batting WHERE "HR" > 30 ORDER BY "HR" DESC, "playerID"',
    'SELECT "teamID", count(*) AS n, sum("HR") AS hr FROM batting GROUP BY "teamID" ORDER BY "teamID"',
    'SELECT b."playerID", a."awardID" FROM batting b '
    'JOIN awards_players a ON b."playerID" = a."playerID" AND b."yearID" = a."yearID" '
    'ORDER BY b."playerID", a."awardID" LIMIT 20',
    'SELECT "playerID", "yearID", '
    'rank() OVER (PARTITION BY "yearID" ORDER BY "HR" DESC) AS r '
    'FROM batting WHERE "yearID" = 2000 ORDER BY r, "playerID" LIMIT 10',
    "SELECT id, double_col * 2 AS d, upper(string_col) AS s "
    "FROM functional_alltypes WHERE bool_col ORDER BY id LIMIT 10",
    'SELECT DISTINCT "lgID" FROM awards_players ORDER BY "lgID"',
    "SELECT t, v FROM mem WHERE v > 1 ORDER BY t",
]


def _register(ctx, data_dir):
    for name in ("batting", "awards_players", "functional_alltypes"):
        ctx.register_parquet(name, [str(data_dir / f"{name}.parquet")])
    batch = pa.record_batch({"t": ["a", "b", "c"], "v": [1, 2, 3]})
    ctx.register_record_batches("mem", [[batch]])
    return ctx


@pytest.fixture
def ctx_pair(data_dir):
    config = SessionConfig().with_target_partitions(4)
    with_ml = _register(SessionContext(config=config), data_dir)
    without_ml = _register(_internal.ml._session_context_without_ml(config), data_dir)
    return with_ml, without_ml


@pytest.mark.parametrize("query", COMPAT_QUERIES)
def test_with_ml_is_inert_for_existing_queries(ctx_pair, query):
    with_ml, without_ml = ctx_pair
    explain = f"EXPLAIN {query}"
    assert (
        with_ml.sql(explain).to_arrow_table()
        == without_ml.sql(explain).to_arrow_table()
    )
    assert with_ml.sql(query).to_arrow_table() == without_ml.sql(query).to_arrow_table()
