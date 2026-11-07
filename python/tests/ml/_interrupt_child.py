"""Child process for test_interrupt.py.

Runs a slow plan through an ML execution path, sends SIGINT to itself from a
timer thread after ``DELAY`` seconds, and prints how long after the signal
the KeyboardInterrupt arrived, then whether the runtime still runs queries.
Usage: python _interrupt_child.py <collect | ml>
"""

import os
import signal
import sys
import threading
import time

from xorq_datafusion import SessionContext
from xorq_datafusion._internal import ml

DELAY = 0.5
SLOW = (
    "SELECT count(*) FROM generate_series(1, 100000) a "
    "CROSS JOIN generate_series(1, 100000) b WHERE (a.value * b.value) % 7 = 3"
)


def main(mode):
    ctx = SessionContext()
    df = ctx.sql(SLOW)
    run = df.collect if mode == "collect" else lambda: ml._collect_interruptible(df)
    sent = []

    def interrupt():
        sent.append(time.monotonic())
        os.kill(os.getpid(), signal.SIGINT)

    threading.Timer(DELAY, interrupt).start()
    try:
        run()
    except KeyboardInterrupt:
        print(f"interrupted {time.monotonic() - sent[0]:.3f}")
    else:
        print("completed")
    rows = ctx.sql("SELECT 41 + 1 AS x").collect()[0].to_pydict()
    print(f"after {rows['x'][0]}")


if __name__ == "__main__":
    main(sys.argv[1])
