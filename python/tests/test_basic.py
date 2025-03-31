

def test_has_all():
    import xorq_datafusion as xdf
    assert all(hasattr(xdf, attr) for attr in xdf.__all__)