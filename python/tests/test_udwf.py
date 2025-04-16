import numpy as np
import pandas as pd
import pyarrow as pa
import pytest

from xorq_datafusion import WindowEvaluator
from xorq_datafusion import udwf


@pytest.fixture
def trades_df():
    # Create sample trading data
    np.random.seed(42)
    dates = pd.date_range(start="2024-01-01", end="2024-01-31", freq="h")

    # Trades data
    trades = pd.DataFrame(
        {
            "timestamp": dates,
            "symbol": np.random.choice(["AAPL", "GOOGL", "MSFT"], len(dates)),
            "price": np.random.uniform(100, 200, len(dates)),
            "volume": np.random.randint(100, 1000, len(dates)),
        }
    )

    return trades


@pytest.fixture
def ctx_trade(ctx, trades_df):
    batch = pa.RecordBatch.from_pandas(trades_df)
    ctx.register_record_batches("trades", [[batch]])
    return ctx


class SmoothTwoColumn(WindowEvaluator):
    """Smooth once column based on a condition of another column.

    If the second column is above a threshold, then smooth over the first column from
    the previous and next rows.
    """

    def __init__(self, alpha: float) -> None:
        self.alpha = alpha

    def evaluate_all(self, values: list[pa.Array], num_rows: int) -> pa.Array:
        results = []
        values_a = values[0]
        values_b = values[1]
        for idx in range(num_rows):
            if not values_b[idx].is_valid:
                if idx == 0:
                    results.append(values_a[1].cast(pa.float64()))
                elif idx == num_rows - 1:
                    results.append(values_a[num_rows - 2].cast(pa.float64()))
                else:
                    results.append(
                        pa.scalar(
                            values_a[idx - 1].as_py() * self.alpha
                            + values_a[idx + 1].as_py() * (1.0 - self.alpha)
                        )
                    )
            else:
                results.append(values_a[idx].cast(pa.float64()))

        return pa.array(results)


def test_udwf_register(ctx_trade):
    # register udwf in bare datafusion
    smooth_two_col = udwf(
        SmoothTwoColumn(0.9),
        [pa.float64(), pa.int64()],
        pa.float64(),
        volatility="immutable",
        name="smooth_two_col",
    )
    ctx_trade.register_udwf(smooth_two_col)

    # create new table with the new computed column
    query = "select trades.*, smooth_two_col(trades.price, trades.volume) over (partition by trades.symbol) as vwap from trades"
    vwap_df = ctx_trade.sql(query).to_pandas()

    assert not vwap_df.empty
