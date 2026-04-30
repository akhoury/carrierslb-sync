def test_main_module_imports():
    """Verify the entrypoint module is importable and exposes main()."""
    from carriers_sync import __main__ as m

    assert callable(m.main)
