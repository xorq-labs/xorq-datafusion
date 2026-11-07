import subprocess
import sys
from pathlib import Path

import pytest

CHILD = Path(__file__).with_name("_interrupt_child.py")
DEADLINE = 2.0


# kmeans: signal after 3 s, once the input is materialized and IterateExec
# is looping.
@pytest.mark.parametrize(
    ("mode", "delay"), [("ml", 0.5), ("fit", 0.5), ("kmeans", 3.0)]
)
def test_ml_execution_is_interruptible(mode, delay):
    out = subprocess.run(
        [sys.executable, str(CHILD), mode, str(delay)],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    ).stdout.split("\n")
    assert out[0].startswith("interrupted "), out
    assert float(out[0].split()[1]) < DEADLINE
    assert out[1] == "after 42"
