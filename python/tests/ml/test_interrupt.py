import subprocess
import sys
from pathlib import Path

import pytest

CHILD = Path(__file__).with_name("_interrupt_child.py")
DEADLINE = 2.0


# kmeans: signal after 3 s, once the input is materialized and IterateExec
# is looping. One partition is the case CI hit: the plan has no repartition
# channels, so its stream never yields, and a signal check that waited for
# it to yield never ran.
@pytest.mark.parametrize(
    ("mode", "delay", "partitions"),
    [
        ("ml", 0.5, 1),
        ("ml", 0.5, 4),
        ("fit", 0.5, 1),
        ("fit", 0.5, 4),
        ("kmeans", 3.0, 1),
        ("kmeans", 3.0, 4),
    ],
)
def test_ml_execution_is_interruptible(mode, delay, partitions):
    out = subprocess.run(
        [sys.executable, str(CHILD), mode, str(delay), str(partitions)],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    ).stdout.split("\n")
    assert out[0].startswith("interrupted "), out
    assert float(out[0].split()[1]) < DEADLINE
    assert out[1] == "after 42"
