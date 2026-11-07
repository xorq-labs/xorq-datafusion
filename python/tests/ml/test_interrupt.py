import subprocess
import sys
from pathlib import Path

CHILD = Path(__file__).with_name("_interrupt_child.py")
DEADLINE = 2.0


def test_ml_execution_is_interruptible():
    out = subprocess.run(
        [sys.executable, str(CHILD), "ml"],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    ).stdout.split("\n")
    assert out[0].startswith("interrupted "), out
    assert float(out[0].split()[1]) < DEADLINE
    assert out[1] == "after 42"
