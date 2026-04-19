def test_rust_extension_loads():
    from sylvan._rust import version

    assert isinstance(version(), str)
    assert version()
