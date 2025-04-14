import pyarrow as pa
import pytest

from xorq_datafusion import udf


@pytest.fixture(scope="function")
def ctx_df(ctx):
    # create a RecordBatch and a new DataFrame from it
    batch = pa.RecordBatch.from_arrays(
        [pa.array([1, 2, 3]), pa.array([4, 4, None])],
        names=["a", "b"],
    )
    ctx.register_record_batches("test_table", [[batch]])
    return ctx


def test_udf(ctx_df):
    # is_null is a pa function over arrays
    is_null = udf(
        lambda x: x.is_null(),
        [pa.int64()],
        pa.bool_(),
        volatility="immutable",
        name="is_null",
    )

    ctx_df.register_udf(is_null)

    result = ctx_df.sql("select is_null(b) from test_table").collect()[0].column(0)

    assert result == pa.array([False, False, True])
