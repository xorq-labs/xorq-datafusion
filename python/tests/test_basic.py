import pyarrow.parquet as pq
import pytest

import xorq_datafusion as xdf


def test_has_all():
    assert all(hasattr(xdf, attr) for attr in xdf.__all__)


def test_register_parquet(data_dir):
    con = xdf.SessionContext()
    con.register_parquet("rownum", [str(data_dir / "data.rownum.parquet")])
    assert con.table("rownum").limit(10) is not None


def test_register_csv(data_dir):
    con = xdf.SessionContext()
    path = str(data_dir / "iris.csv")
    con.register_csv("iris", [path])
    assert con.sql("SELECT sepal_length FROM iris LIMIT 10") is not None


def test_write_parquet_compression(tmp_path):
    df = xdf.SessionContext().sql("SELECT * FROM (VALUES (1), (2), (3)) t(x)")
    path = tmp_path / "out.parquet"
    df.write_parquet(str(path), "zstd(3)")
    meta = pq.ParquetFile(path).metadata.row_group(0).column(0)
    assert (pq.read_table(path).to_pydict(), meta.compression) == (
        {"x": [1, 2, 3]},
        "ZSTD",
    )
    with pytest.raises(ValueError, match="unsupported parquet compression: bogus"):
        df.write_parquet(str(tmp_path / "bad.parquet"), "bogus")
