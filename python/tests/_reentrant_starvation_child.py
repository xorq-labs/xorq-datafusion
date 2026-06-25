"""Subprocess helper for the worker-starvation regression.

Invoked via ``sys.executable`` by
``test_runtime_within_runtime.py::test_reentrant_execute_stream_single_worker_does_not_deadlock``.
It lives in its own process because the fix it exercises depends on the tokio
runtime having exactly one worker, and the worker pool is sized from
``available_parallelism()`` the first time the runtime is built -- so the CPU
affinity has to be narrowed *before* ``xorq_datafusion`` is imported, which an
in-process test cannot do.

With one worker, a multi-partition outer query makes ``CoalescePartitionsExec``
spawn the per-partition ``ProjectionExec`` (which runs the UDF) onto that
worker; the UDF re-enters another context via ``execute_stream``, whose block
site (``wait_for_completion``) parks the worker. Without the ``block_in_place``
handoff there is no thread left to drive the spawned inner task, so the query
deadlocks and the parent test times out. The UDF body mirrors the in-process
``test_udf_reentry_returns_inner_count``.

Prints ``OK <row count>`` on success or ``SKIP`` if affinity cannot be pinned.
Underscore-prefixed so pytest does not collect it.
"""

import os


def main():
    try:
        os.sched_setaffinity(0, {sorted(os.sched_getaffinity(0))[0]})
    except (AttributeError, OSError):
        print("SKIP")
        return 0

    import pyarrow as pa  # noqa: PLC0415

    from xorq_datafusion import SessionContext, udf  # noqa: PLC0415

    schema = pa.schema([("id", pa.int64())])

    inner = SessionContext()
    inner.register_record_batches(
        "inner_t",
        [
            [
                pa.record_batch(
                    {"id": pa.array([1, 2, 3], type=pa.int64())}, schema=schema
                )
            ]
        ],
    )

    def body(arr):
        stream = inner.sql("select id from inner_t").execute_stream()
        n = sum(len(b.to_pyarrow()) for b in stream)
        return pa.array([n] * len(arr), type=pa.int64())

    fn = udf(
        body,
        input_types=[pa.int64()],
        return_type=pa.int64(),
        volatility="volatile",
        name="rs_udf",
    )

    outer = SessionContext()
    # Multiple partitions -> CoalescePartitionsExec spawns the UDF onto the worker.
    outer.register_record_batches(
        "t",
        [
            [pa.record_batch({"id": pa.array([i], type=pa.int64())}, schema=schema)]
            for i in range(4)
        ],
    )
    outer.register_udf(fn)

    rows = outer.sql("select rs_udf(id) v from t").collect()
    print("OK", sum(len(b) for b in rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
