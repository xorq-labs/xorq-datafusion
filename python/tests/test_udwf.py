import threading

import numpy as np
import pandas as pd
import pyarrow as pa
import pytest

from xorq_datafusion import WindowEvaluator, WindowUDF, udwf


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


class CallCounter(WindowEvaluator):
    """Stateful: returns how many times this evaluator object has run."""

    def __init__(self):
        self.calls = 0

    def evaluate_all(self, values, num_rows):
        self.calls += 1
        return pa.array([self.calls] * num_rows, pa.int64())


@pytest.fixture
def ctx_groups(ctx):
    ctx.register_record_batches(
        "g",
        [
            [
                pa.RecordBatch.from_arrays(
                    [pa.array([1, 2, 3, 4, 5, 6]), pa.array([0, 1, 2, 0, 1, 2])],
                    names=["a", "k"],
                )
            ]
        ],
    )
    return ctx


def _calls_per_row(ctx, func, name="calls"):
    ctx.register_udwf(udwf(func, [pa.int64()], pa.int64(), "immutable", name))
    table = ctx.sql(
        f"select {name}(a) over (partition by k) as c from g"
    ).to_arrow_table()
    return table.column("c").to_pylist()


@pytest.mark.parametrize(
    "make_func",
    [
        pytest.param(CallCounter, id="instance"),
        pytest.param(lambda: CallCounter, id="class"),
        pytest.param(lambda: lambda: CallCounter(), id="function"),
    ],
)
def test_each_window_partition_gets_its_own_evaluator(ctx_groups, make_func):
    """Three window partitions: a shared evaluator would count 1, 2 and 3."""
    func = make_func()
    assert _calls_per_row(ctx_groups, func) == [1] * 6


def test_registered_instance_is_not_mutated(ctx_groups):
    evaluator = CallCounter()
    _calls_per_row(ctx_groups, evaluator)
    assert evaluator.calls == 0


def test_window_udf_constructor_copies_instances(ctx_groups):
    """WindowUDF(...) called directly with an instance, as xorq does."""
    ctx_groups.register_udwf(
        WindowUDF("direct", CallCounter(), [pa.int64()], pa.int64(), "immutable")
    )
    table = ctx_groups.sql(
        "select direct(a) over (partition by k) as c from g"
    ).to_arrow_table()
    assert table.column("c").to_pylist() == [1] * 6


class Uncopyable(CallCounter):
    def __init__(self):
        super().__init__()
        self.lock = threading.Lock()


def test_uncopyable_instance_asks_for_a_factory(ctx_groups):
    with pytest.raises(Exception, match="pass a factory"):
        _calls_per_row(ctx_groups, Uncopyable())


def test_uncopyable_evaluator_works_through_a_factory(ctx_groups):
    assert _calls_per_row(ctx_groups, Uncopyable) == [1] * 6


@pytest.mark.parametrize(
    ("func", "expected"),
    [
        pytest.param(CallCounter(), "callcounter", id="instance"),
        pytest.param(CallCounter, "callcounter", id="class"),
    ],
)
def test_udwf_default_name(func, expected):
    assert repr(udwf(func, [pa.int64()], pa.int64(), "immutable")) == (
        f"WindowUDF({expected})"
    )


def test_udwf_rejects_non_callable():
    with pytest.raises(TypeError, match="callable returning one"):
        udwf(42, [pa.int64()], pa.int64(), "immutable")
