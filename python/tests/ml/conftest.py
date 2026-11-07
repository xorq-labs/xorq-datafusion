import pytest

from xorq_datafusion import SessionConfig, SessionContext

pytest.importorskip("sklearn")


@pytest.fixture
def ctx():
    return SessionContext(SessionConfig().with_target_partitions(4))
