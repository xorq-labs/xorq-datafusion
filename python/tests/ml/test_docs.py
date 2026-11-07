import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[3]
README = (ROOT / "README.md").read_text()
DEMO = ROOT / "examples" / "ml_demo.py"


def layers():
    section = README.split("## ML (experimental)", 1)[1].split("\n## ", 1)[0]
    return re.findall(r"^\d+\. `([^`]+)` — (.+?):", section, flags=re.MULTILINE)


def test_readme_walkthrough_matches_the_code():
    entries = layers()
    assert len(entries) >= 10
    for path, symbols in entries:
        source = (ROOT / path).read_text()
        for symbol in re.findall(r"`(\w+)`", symbols):
            definition = rf"\b(fn|struct|enum|trait|class|def)\s+{symbol}\b"
            assert re.search(definition, source), f"{symbol} is not defined in {path}"


def test_demo_runs_and_matches_sklearn():
    out = subprocess.run(
        [sys.executable, str(DEMO)],
        capture_output=True,
        text=True,
        timeout=300,
        check=True,
    ).stdout
    assert "matches scikit-learn" in out
