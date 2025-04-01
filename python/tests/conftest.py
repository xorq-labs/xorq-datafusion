from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def data_dir():
    return (Path(__file__).parents[2] / "data").resolve()
