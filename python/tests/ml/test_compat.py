import subprocess
import sys

import xorq_datafusion.ml as ml
from xorq_datafusion import _internal


def _run(code):
    return subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    ).stdout.strip()


def test_base_import_does_not_load_sklearn():
    out = _run(
        "import sys, xorq_datafusion; "
        "print('sklearn' in sys.modules, 'xorq_datafusion.ml' in sys.modules)"
    )
    assert out == "False False"


def test_ml_public_names():
    assert set(ml.__all__) == {
        "Model",
        "Reason",
        "Supported",
        "Unsupported",
        "compile",
        "fit",
        "supports",
    }


def test_native_ml_submodule_registered():
    assert hasattr(_internal, "ml")
