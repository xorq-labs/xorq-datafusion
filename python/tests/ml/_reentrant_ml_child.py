"""Child process for test_interrupt.py::test_ml_entry_point_reentered_on_one_worker.

A Python UDF evaluated on a tokio worker calls an ML entry point
(``_collect_interruptible``, the path ``ml.fit`` takes). The runtime is
narrowed to one worker before ``xorq_datafusion`` is imported (the worker
count is sized once, from the CPU affinity), so the nested call's spawned
task can only run if the waiting worker hands its core back. A hang is
detected by the parent's timeout. Prints ``rows <n>`` on success.
"""

import os

if hasattr(os, "sched_setaffinity"):
    os.sched_setaffinity(0, {sorted(os.sched_getaffinity(0))[0]})

import pyarrow as pa

from xorq_datafusion import SessionContext, udf
from xorq_datafusion._internal import ml

inner = SessionContext()


def nested(values: pa.Array) -> pa.Array:
    rows = sum(
        b.num_rows for b in ml._collect_interruptible(inner.sql("SELECT 1 AS one"))
    )
    return pa.array([rows] * len(values), pa.int64())


def main():
    outer = SessionContext()
    outer.register_udf(udf(nested, [pa.int64()], pa.int64(), "volatile", name="nested"))
    outer.register_record_batches("t", [[pa.record_batch({"a": [1, 2, 3]})]])
    batches = ml._collect_interruptible(outer.sql("SELECT nested(a) AS n FROM t"))
    print("rows", sum(b.num_rows for b in batches))


if __name__ == "__main__":
    main()
