import xorq_datafusion as xdf


def test_has_all():
    assert all(hasattr(xdf, attr) for attr in xdf.__all__)


def test_register_parquet(data_dir):
    con = xdf.SessionContext()
    con.register_parquet("rownum", str(data_dir / "data.rownum.parquet"))
    assert con.table("rownum").limit(10) is not None


def test_register_csv(data_dir):
    con = xdf.SessionContext()
    con.register_csv("iris", str(data_dir / "iris.csv"))
    assert con.sql("SELECT sepal_length FROM iris LIMIT 10") is not None
