"""Property tests for batchcorder's CastingStreamCache (the `.cast()` path).

A `pa.RecordBatchReader` is single-use. `batchcorder.StreamCache` makes it
replayable; `StreamCache.cast(schema)` wraps it as a `CastingStreamCache` whose
`__arrow_c_stream__` yields a *fresh* reader on every call. That fresh-reader-
per-call contract is exactly what DataFusion needs to scan one registered table
more than once (self-joins, k-way joins, UNION ALL).

`test_context.py` pins this with a single fixed self-join example. These tests
generalise it: a unique-id table self-joined k ways must always return exactly
`len(ids)` rows with matching values, for arbitrary data and arbitrary k.

`batchcorder` is optional; the whole module skips cleanly without it.
"""

import pyarrow as pa
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from tests.strategies import unique_id_val_table
from xorq_datafusion import SessionContext

StreamCache = pytest.importorskip("batchcorder").StreamCache


_SCHEMA = pa.schema([("id", pa.int64()), ("val", pa.float64())])

# k for a k-way self-join. Each join arm is one independent scan of the
# registered table, so this directly exercises the fresh-reader-per-scan replay.
_join_arity = st.integers(min_value=2, max_value=4)


def _casting_cache(ids, vals, batch_size):
    """A CastingStreamCache over (id, val) rows, chunked into batch_size batches."""

    def _batches():
        for start in range(0, len(ids), batch_size):
            sl = slice(start, start + batch_size)
            yield pa.record_batch(
                {
                    "id": pa.array(ids[sl], type=pa.int64()),
                    "val": pa.array(vals[sl], type=pa.float64()),
                },
                schema=_SCHEMA,
            )

    reader = pa.RecordBatchReader.from_batches(_SCHEMA, _batches())
    # .cast(schema) -> CastingStreamCache: a fresh reader on every scan.
    return StreamCache(reader).cast(_SCHEMA)


@given(unique_id_val_table(), st.integers(min_value=1, max_value=128))
@settings(max_examples=30, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_self_join_pairs_each_row_with_itself(data, batch_size):
    """Self-join on a unique key returns one row per id, with both sides equal.

    Requires two independent scans of the cache; the CastingStreamCache must
    replay the full stream for the second arm.
    """
    ids, vals = data

    ctx = SessionContext()
    ctx.register_record_batch_reader("t", _casting_cache(ids, vals, batch_size))

    rows = ctx.sql(
        "SELECT l.id AS id, l.val AS lval, r.val AS rval "
        "FROM t AS l JOIN t AS r ON l.id = r.id"
    ).collect()
    table = pa.Table.from_batches(
        rows,
        schema=pa.schema(
            [("id", pa.int64()), ("lval", pa.float64()), ("rval", pa.float64())]
        ),
    )

    assert table.num_rows == len(ids)
    assert table.column("lval").to_pylist() == table.column("rval").to_pylist()
    assert sorted(table.column("id").to_pylist()) == sorted(ids)


@given(unique_id_val_table(), _join_arity)
@settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_k_way_self_join_row_count_is_independent_of_k(data, k):
    """A k-way self-join on a unique key always returns exactly len(ids) rows,
    regardless of k. Each arm is a fresh scan, so this pins replay across k scans.
    """
    ids, vals = data

    ctx = SessionContext()
    ctx.register_record_batch_reader("t", _casting_cache(ids, vals, 64))

    arms = " ".join(f"JOIN t AS t{i} ON t0.id = t{i}.id" for i in range(1, k))
    rows = ctx.sql(f"SELECT count(*) AS c FROM t AS t0 {arms}").collect()
    assert rows[0].column("c")[0].as_py() == len(ids)


@given(unique_id_val_table())
@settings(max_examples=30, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_cast_cache_preserves_aggregates(data):
    """Scanning a CastingStreamCache once reproduces the source aggregates,
    confirming the cast wrapper neither drops nor mutates rows."""
    ids, vals = data

    ctx = SessionContext()
    ctx.register_record_batch_reader("t", _casting_cache(ids, vals, 64))

    rb = ctx.sql("SELECT count(id) AS c, sum(id) AS s FROM t").collect()[0]
    assert rb.column("c")[0].as_py() == len(ids)
    assert rb.column("s")[0].as_py() == (sum(ids) if ids else None)


class _StreamCacheProvider:
    """A Python TableProvider backed by a batchcorder StreamCache.

    Each scan returns a fresh reader (`cache.cast(schema)` yields one per call),
    so DataFusion can scan the registered table more than once. This is the
    provider-wraps-cache shape: replay lives in the cache, not in DataFusion.
    """

    def __init__(self, cache, schema):
        self.cache = cache
        self._schema = schema

    def schema(self):
        return self._schema

    def scan(self, filters=None):
        return pa.RecordBatchReader.from_stream(self.cache.cast(self._schema))


def _stream_cache(ids, vals, batch_size):
    """A replayable StreamCache over (id, val) rows."""

    def _batches():
        for start in range(0, len(ids), batch_size):
            sl = slice(start, start + batch_size)
            yield pa.record_batch(
                {
                    "id": pa.array(ids[sl], type=pa.int64()),
                    "val": pa.array(vals[sl], type=pa.float64()),
                },
                schema=_SCHEMA,
            )

    return StreamCache(pa.RecordBatchReader.from_batches(_SCHEMA, _batches()))


@given(unique_id_val_table())
@settings(max_examples=30, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_provider_wrapping_streamcache_single_scan(data):
    """A TableProvider that hands out cache-backed readers reproduces the source
    rows on a single scan."""
    ids, vals = data

    ctx = SessionContext()
    ctx.register_table_provider(
        "t", _StreamCacheProvider(_stream_cache(ids, vals, 64), _SCHEMA)
    )

    rb = ctx.sql("SELECT count(id) AS c, sum(id) AS s FROM t").collect()[0]
    assert rb.column("c")[0].as_py() == len(ids)
    assert rb.column("s")[0].as_py() == (sum(ids) if ids else None)


@given(unique_id_val_table())
@settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_provider_wrapping_streamcache_self_join_replays(data):
    """Self-joining the provider table calls scan twice; the wrapped StreamCache
    must replay so the second scan still sees the full stream."""
    ids, vals = data

    ctx = SessionContext()
    ctx.register_table_provider(
        "t", _StreamCacheProvider(_stream_cache(ids, vals, 64), _SCHEMA)
    )

    rows = ctx.sql(
        "SELECT count(*) AS c FROM t AS l JOIN t AS r ON l.id = r.id"
    ).collect()
    assert rows[0].column("c")[0].as_py() == len(ids)
