"""Hypothesis strategies for xorq_datafusion.

Focuses on execute_stream / collect equivalence across UDF and UDAF return types,
including binary variants that have triggered C Data interface failures.
"""

import pickle
import uuid

import pyarrow as pa
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Atomic: Arrow scalar types to test as UDF/UDAF return types
# ---------------------------------------------------------------------------

# Types that the C Data interface must round-trip correctly.
# Binary variants are the known failure class; numeric/string included as
# regression guard so we know when a fix breaks previously-working types.
SCALAR_RETURN_TYPES = [
    pa.binary(),
    pa.large_binary(),
    pa.int32(),
    pa.int64(),
    pa.float32(),
    pa.float64(),
    pa.utf8(),
    pa.large_utf8(),
    pa.bool_(),
]

arrow_return_type = st.sampled_from(SCALAR_RETURN_TYPES)

# Input column is always float64 — simple, widely supported, avoids
# distraction from the type under test (the return type).
INPUT_TYPE = pa.float64()


# ---------------------------------------------------------------------------
# Composite: record batches with float64 column(s)
# ---------------------------------------------------------------------------


@st.composite
def float64_record_batch(draw, min_cols=1, max_cols=4, min_rows=1, max_rows=20):
    """RecordBatch with 1-4 float64 columns and 1-20 rows."""
    n_cols = draw(st.integers(min_value=min_cols, max_value=max_cols))
    n_rows = draw(st.integers(min_value=min_rows, max_value=max_rows))
    cols = [
        pa.array(
            draw(
                st.lists(
                    st.floats(allow_nan=False, allow_infinity=False),
                    min_size=n_rows,
                    max_size=n_rows,
                )
            )
        )
        for _ in range(n_cols)
    ]
    names = [f"f{i}" for i in range(n_cols)]
    return pa.RecordBatch.from_arrays(cols, names=names)


# ---------------------------------------------------------------------------
# Helpers: build pyarrow scalar / array of any supported return type
# ---------------------------------------------------------------------------


def _make_value(return_type: pa.DataType, n: int) -> pa.Array:
    """Return a length-n array of `return_type` with simple deterministic values."""
    if pa.types.is_binary(return_type) or pa.types.is_large_binary(return_type):
        data = [pickle.dumps(i) for i in range(n)]
    elif pa.types.is_integer(return_type):
        data = list(range(n))
    elif pa.types.is_floating(return_type):
        data = [float(i) for i in range(n)]
    elif pa.types.is_string(return_type) or pa.types.is_large_string(return_type):
        data = [str(i) for i in range(n)]
    elif pa.types.is_boolean(return_type):
        data = [i % 2 == 0 for i in range(n)]
    else:
        raise ValueError(f"Unsupported return type: {return_type}")
    return pa.array(data, type=return_type)


def _make_scalar(return_type: pa.DataType) -> pa.Scalar:
    """Return a single pa.Scalar of `return_type`."""
    return _make_value(return_type, 1)[0]


# ---------------------------------------------------------------------------
# UDF factory: scalar function that maps float64 columns → return_type array
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Composite: row data for a batchcorder.StreamCache-backed int64 table
# ---------------------------------------------------------------------------


@st.composite
def int64_stream_data(draw, max_rows=5000):
    """(values, batch_size) modelling valid input to ``StreamCache``.

    Models what a caller feeds a ``batchcorder.StreamCache``: an int64
    RecordBatchReader plus the batch size used to chunk it. Constraints:

    - ``batch_size`` floored at 50 so we don't generate tens of thousands of
      single-row Arrow batches (the cache stores one entry per batch).
    - ``max_rows`` capped (default 5000) so concurrent/threaded tests that
      fan out N readers over this data stay well within their timeout.
    - values are tiled from a small *unique* base list (>= 2 distinct), so
      sum/max/count are non-trivial without blowing up the example size.

    Empty (``n_rows == 0``) is included on purpose: it is the boundary where a
    StreamCache produces zero batches and aggregates return NULL.
    """
    n_rows = draw(st.integers(min_value=0, max_value=max_rows))
    base = draw(
        st.lists(
            st.integers(min_value=-1000, max_value=1000),
            min_size=2,
            max_size=64,
            unique=True,
        )
    )
    values = (base * (n_rows // len(base) + 1))[:n_rows]
    batch_size = draw(st.integers(min_value=50, max_value=2000))
    return values, batch_size


# Number of concurrent workers / fan-out readers. Kept small: every worker is
# a real OS thread running a DataFusion query, so the search space is in the
# interaction (interleaving), not in raw thread count.
worker_count = st.integers(min_value=2, max_value=6)


# ---------------------------------------------------------------------------
# Composite: rows for a context that a re-entrant TableProvider.scan re-queries
# ---------------------------------------------------------------------------


@st.composite
def int64_table_values(draw, max_rows=2000):
    """A single int64 column's worth of rows registered in a context.

    Models the data a re-entrant ``TableProvider.scan`` reads back out of
    *another* ``SessionContext`` while the outer context is mid-``block_on``.
    Values are tiled from a small *unique* base list so the multiset has
    duplicates without large example sizes. Empty (``n_rows == 0``) is included:
    it is the boundary where the inner scan yields zero batches.
    """
    n_rows = draw(st.integers(min_value=0, max_value=max_rows))
    base = draw(
        st.lists(
            st.integers(min_value=-1000, max_value=1000),
            min_size=1,
            max_size=64,
            unique=True,
        )
    )
    return (base * (n_rows // len(base) + 1))[:n_rows]


# Depth of a chain of re-entrant TableProviders: each provider's scan queries
# the next context down, so a depth-k chain nests block_in_place k levels deep.
# 1 = a single re-entry; >1 stresses repeated nesting.
nesting_depth = st.integers(min_value=1, max_value=4)


# ---------------------------------------------------------------------------
# Composite: (ids, vals) for a self-joinable table backed by a StreamCache
# ---------------------------------------------------------------------------


@st.composite
def unique_id_val_table(draw, max_rows=300):
    """(ids, vals) where ids are unique int64 and vals are finite float64.

    Unique ids mean a self-join on ``id`` yields exactly one match per row, so
    a k-way self-join returns exactly ``len(ids)`` rows regardless of k. This
    makes the row count an exact, k-independent oracle for the replay contract
    of ``batchcorder``'s ``CastingStreamCache`` (a fresh reader per scan).

    ``max_rows`` is modest because a self-join materialises pairs. Empty is
    included: zero scans of zero rows must still join to zero rows.
    """
    n = draw(st.integers(min_value=0, max_value=max_rows))
    ids = list(range(n))  # unique by construction
    vals = draw(
        st.lists(
            st.floats(allow_nan=False, allow_infinity=False),
            min_size=n,
            max_size=n,
        )
    )
    return ids, vals


# LIMIT applied to a teardown query. 0 is valid SQL (empty result) and is a
# distinct teardown path, so it is included.
limit_value = st.integers(min_value=0, max_value=200)


def make_udf_func(return_type: pa.DataType):
    """Return a Python callable suitable for xorq_datafusion.udf."""

    def func(*args):
        n = len(args[0])
        return _make_value(return_type, n)

    func.__name__ = f"udf_func_{return_type}"
    return func


# ---------------------------------------------------------------------------
# UDAF factory: accumulator class with binary state, configurable return type
# ---------------------------------------------------------------------------


def make_accumulator_class(return_type: pa.DataType):
    """Dynamically create an Accumulator subclass for the given return type."""
    from xorq_datafusion import Accumulator

    class DynAccumulator(Accumulator):
        def __init__(self):
            self._count = 0

        def state(self) -> list[pa.Scalar]:
            # State is always binary (serialised int counter).
            return [pa.scalar(pickle.dumps(self._count), type=pa.binary())]

        def update(self, values: pa.Array) -> None:
            self._count += len(values)

        def merge(self, states: pa.Array) -> None:
            for s in states:
                if s.is_valid:
                    self._count += pickle.loads(s.as_py())

        def evaluate(self) -> pa.Scalar:
            return _make_scalar(return_type)

    DynAccumulator.__name__ = f"Accum_{return_type}"
    return DynAccumulator


# ---------------------------------------------------------------------------
# Composite: fully-wired (ctx, df, return_type) ready to call execute_stream
# ---------------------------------------------------------------------------


@st.composite
def udf_dataframe(draw):
    """SessionContext + DataFrame for a UDF that returns a varied type.

    Draws: return type, input batch shape.
    Returns: (ctx, df, return_type) — caller should not mutate ctx further.
    """
    import xorq_datafusion as xdf

    return_type = draw(arrow_return_type)
    batch = draw(float64_record_batch())
    n_cols = batch.num_columns
    col_names = batch.schema.names
    uid = uuid.uuid4().hex[:8]

    ctx = xdf.SessionContext()
    ctx.register_record_batches(f"t_{uid}", [[batch]])

    func = make_udf_func(return_type)
    fn = xdf.udf(
        func,
        input_types=[INPUT_TYPE] * n_cols,
        return_type=return_type,
        volatility="volatile",
        name=f"udf_{uid}",
    )
    ctx.register_udf(fn)

    cols_sql = ", ".join(col_names)
    df = ctx.sql(f"SELECT udf_{uid}({cols_sql}) AS result FROM t_{uid}")
    return ctx, df, return_type


@st.composite
def udaf_dataframe(draw):
    """SessionContext + DataFrame for a UDAF that returns a varied type.

    Returns: (ctx, df, return_type).
    """
    import xorq_datafusion as xdf

    return_type = draw(arrow_return_type)
    batch = draw(float64_record_batch(min_cols=1, max_cols=1))
    uid = uuid.uuid4().hex[:8]

    ctx = xdf.SessionContext()
    ctx.register_record_batches(f"t_{uid}", [[batch]])

    accum_cls = make_accumulator_class(return_type)
    agg = xdf.udaf(
        accum_cls,
        input_type=[INPUT_TYPE],
        return_type=return_type,
        state_type=[pa.binary()],
        volatility="volatile",
        name=f"udaf_{uid}",
    )
    ctx.register_udaf(agg)

    df = ctx.sql(f"SELECT udaf_{uid}(f0) AS result FROM t_{uid}")
    return ctx, df, return_type
