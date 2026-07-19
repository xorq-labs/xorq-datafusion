"""Subprocess helper for the streaming re-entrant-chain starvation regression.

Invoked via ``sys.executable`` by
``test_runtime_within_runtime.py::test_reentrant_stream_chain_low_cores_does_not_deadlock``.
It lives in its own process because (1) the tokio worker count is sized from
``available_parallelism()`` the first time the runtime is built, so it must be
narrowed *before* ``xorq_datafusion`` is imported, and (2) a deadlock here can
strand threads mid-GIL, so only an out-of-process timeout is a reliable hang
detector -- an in-process watchdog could itself be starved.

Failure mode it guards
----------------------
An ``AbstractTableProvider`` whose ``scan()`` drains a nested ``execute_stream``
over the same context, stacked ``depth`` levels deep and driven from the top by
another ``execute_stream``. Each level's provider stream is pulled while the
level above blocks waiting for it, so a chain deeper than the worker count needs
that many workers live at once. When the pull blocks a tokio worker without
handing its core back (the pre-fix ``thread::scope``/``join`` in
``ibis_table_exec``) a chain with ``depth > workers`` starves the runtime and
the outer query hangs forever.

The chain is sized to ``workers + 2`` so it overshoots the ``depth > workers``
threshold with margin (not the razor's-edge ``workers + 1``), making the pre-fix
deadlock deterministic regardless of scheduler jitter. On Linux the runtime is
pinned to two workers first so ``depth`` stays a small, fast ``4``; elsewhere it
falls back to the box's own core count so the test still runs (no hard
dependency on ``sched_setaffinity``).

Beyond "did not hang" it re-materialises the streamed result and checks the
exact rows -- each level adds ``x{i} = a + i`` -- so a silent wrong-result
regression in the spawn_blocking reader / channel / projection path also fails.

Drive mode / shape
------------------
``argv[1]`` selects how the *outer* query is consumed: ``stream`` (default),
``partitioned`` (``execute_stream_partitioned``), or ``collect``. All three
deadlock before the fix -- the nested per-level polls run on workers regardless
of how the top is drained -- so each exercises a distinct outer bridge
(``execute_stream`` / ``execute_stream_partitioned`` / ``collect``) over the
same starvation setup.

``argv[2]`` selects the plan shape: ``chain`` (default, one linear chain) or
``join`` (two independent chains joined on ``a``, so a multi-child plan
re-enters once per side within a single outer query).

Output contract
---------------
``OK depth=<d> rows=<n> checksum=<c>`` on success, or ``SKIP`` when fewer than
two workers can be secured (the starvation precondition needs ``workers >= 2``).
Underscore-prefixed so pytest does not collect it.
"""

import os
import sys


def _worker_count():
    """Best effort at the tokio worker count == available_parallelism.

    Pin to two CPUs when we can so the chain stays short (depth 4); otherwise
    report the box's own core budget. Returns None when it cannot secure >= 2.
    """
    try:
        available = sorted(os.sched_getaffinity(0))
        if len(available) < 2:
            return None
        os.sched_setaffinity(0, set(available[:2]))
        return 2
    except (AttributeError, OSError):
        pass
    # No affinity control (e.g. macOS/Windows): use the natural core count.
    cpus = os.cpu_count() or 1
    return cpus if cpus >= 2 else None


def main():
    workers = _worker_count()
    if workers is None:
        print("SKIP")
        return 0
    depth = workers + 2  # overshoot depth > workers with margin

    import pyarrow as pa  # noqa: PLC0415

    from xorq_datafusion import AbstractTableProvider, SessionContext  # noqa: PLC0415

    class SqlReentrantProvider(AbstractTableProvider):
        """scan() re-enters ``ctx`` by streaming an upstream SQL query."""

        def __init__(self, ctx, sql, schema):
            self.ctx = ctx
            self.sql = sql
            self._schema = schema

        def schema(self):
            return self._schema

        def scan(self, filters=None):
            frame = self.ctx.sql(self.sql)  # re-enter the same SessionContext

            def gen():
                for batch in frame.execute_stream():  # drain the nested stream
                    yield batch.to_pyarrow()

            return pa.RecordBatchReader.from_batches(self._schema, gen())

    base_values = [1, 2, 3, 4, 5]
    ctx = SessionContext()

    def build_chain(prefix, colprefix):
        """Register a base table + ``depth`` re-entrant levels; return top name.

        Each level adds ``{colprefix}{i} = a + i``. ``prefix`` namespaces the
        table names so several chains can live in one context (for the join
        shape). The expected value of every added column is ``a + i``.
        """
        base = pa.record_batch({"a": pa.array(base_values, pa.int64())})
        ctx.register_record_batches(f"{prefix}base", [[base]])
        schema = base.schema
        name = f"{prefix}base"
        for i in range(depth):
            col = f"{colprefix}{i}"
            schema = schema.append(pa.field(col, pa.int64()))
            next_name = f"{prefix}lvl{i}"
            ctx.deregister_table(next_name)
            ctx.register_table_provider(
                next_name,
                SqlReentrantProvider(
                    ctx, f"SELECT *, a + {i} AS {col} FROM {name}", schema
                ),
            )
            name = next_name
        return name

    drive = sys.argv[1] if len(sys.argv) > 1 else "stream"
    shape = sys.argv[2] if len(sys.argv) > 2 else "chain"

    # Expected columns: a, plus the per-level added columns. The join shape
    # combines two independent re-entrant chains, so both re-enter within one
    # outer query (a multi-child plan re-enters per side).
    expected = {"a": sorted(base_values)}
    if shape == "chain":
        top = build_chain("", "x")
        sql = f"SELECT * FROM {top}"
        for i in range(depth):
            expected[f"x{i}"] = sorted(v + i for v in base_values)
    elif shape == "join":
        left = build_chain("l", "x")
        right = build_chain("r", "y")
        sql = f"SELECT * FROM {left} JOIN {right} USING (a)"
        for i in range(depth):
            expected[f"x{i}"] = sorted(v + i for v in base_values)
            expected[f"y{i}"] = sorted(v + i for v in base_values)
    else:
        raise ValueError(f"unknown shape: {shape!r}")

    frame = ctx.sql(sql)
    if drive == "stream":
        batches = [b.to_pyarrow() for b in frame.execute_stream()]
    elif drive == "partitioned":
        batches = [
            b.to_pyarrow()
            for stream in frame.execute_stream_partitioned()
            for b in stream
        ]
    elif drive == "collect":
        batches = frame.collect()
    else:
        raise ValueError(f"unknown drive mode: {drive!r}")
    table = pa.Table.from_batches(batches)

    actual = {c: sorted(table.column(c).to_pylist()) for c in table.column_names}
    assert actual == expected, f"wrong result: {actual} != {expected}"

    checksum = sum(sum(vals) for vals in actual.values())
    print(f"OK depth={depth} rows={table.num_rows} checksum={checksum}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
