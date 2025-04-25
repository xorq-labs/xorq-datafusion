from pathlib import Path

import pytest

from xorq_datafusion import SessionContext


@pytest.fixture(scope="session")
def data_dir():
    return (Path(__file__).parents[2] / "data").resolve()


@pytest.fixture(scope="function")
def ctx():
    return SessionContext()
