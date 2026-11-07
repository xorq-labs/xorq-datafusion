"""Child process for test_interrupt.py.

Runs a slow plan through an ML execution path, sends SIGINT to itself from a
timer thread after ``DELAY`` seconds, and prints how long after the signal
the KeyboardInterrupt arrived, then whether the runtime still runs queries.
Usage: python _interrupt_child.py <collect | ml | fit | kmeans>
"""

import json
import os
import signal
import sys
import threading
import time

from xorq_datafusion import SessionContext
from xorq_datafusion._internal import ml

DELAY = 0.5
SLOW_INPUT = (
    "SELECT CAST(a.value * b.value AS DOUBLE) AS x FROM generate_series(1, 100000) a "
    "CROSS JOIN generate_series(1, 100000) b"
)
SCALER_FIT = {
    "features": ["x"],
    "steps": [{"kind": "standard_scaler", "with_mean": True, "with_std": True}],
}
# Enough rows that each KMeans iteration takes a while; tol=0 and a huge
# max_iter keep the loop running, so the signal lands inside IterateExec.
KMEANS_INPUT = (
    "SELECT CAST(value % 1009 AS DOUBLE) AS a, CAST((value * 7) % 1013 AS DOUBLE) AS b "
    "FROM generate_series(1, 1000000)"
)
KMEANS_FIT = {
    "features": ["a", "b"],
    "steps": [
        {
            "kind": "kmeans",
            "n_clusters": 3,
            "init": [[0.0, 0.0], [500.0, 500.0], [1000.0, 1000.0]],
            "max_iter": 100000,
            "tol": 0.0,
        }
    ],
}
SLOW = (
    "SELECT count(*) FROM generate_series(1, 100000) a "
    "CROSS JOIN generate_series(1, 100000) b WHERE (a.value * b.value) % 7 = 3"
)


def main(mode, delay):
    ctx = SessionContext()
    df = ctx.sql(SLOW)
    runs = {
        "collect": df.collect,
        "ml": lambda: ml._collect_interruptible(df),
        "fit": lambda: ml.fit(ctx.sql(SLOW_INPUT), json.dumps(SCALER_FIT)),
        "kmeans": lambda: ml.fit(ctx.sql(KMEANS_INPUT), json.dumps(KMEANS_FIT)),
    }
    run = runs[mode]
    sent = []

    def interrupt():
        sent.append(time.monotonic())
        os.kill(os.getpid(), signal.SIGINT)

    threading.Timer(delay, interrupt).start()
    try:
        run()
    except KeyboardInterrupt:
        print(f"interrupted {time.monotonic() - sent[0]:.3f}")
    else:
        print("completed")
    rows = ctx.sql("SELECT 41 + 1 AS x").collect()[0].to_pydict()
    print(f"after {rows['x'][0]}")


if __name__ == "__main__":
    main(sys.argv[1], float(sys.argv[2]) if len(sys.argv) > 2 else DELAY)
