import logging

from carriers_sync.logging_setup import configure_logging, register_secret


def test_configure_logging_sets_root_level():
    configure_logging("debug", secrets=[])
    assert logging.getLogger().level == logging.DEBUG


def test_configure_logging_maps_ha_levels_to_python():
    configure_logging("notice", secrets=[])
    assert logging.getLogger().level == logging.INFO

    configure_logging("trace", secrets=[])
    assert logging.getLogger().level == logging.DEBUG


def test_credential_redactor_strips_secrets(caplog):
    configure_logging("info", secrets=["super_secret_pw"])
    log = logging.getLogger("test")
    with caplog.at_level(logging.INFO):
        log.info("connecting with password=super_secret_pw to alfa")
    assert "super_secret_pw" not in caplog.text
    assert "***" in caplog.text


def test_register_secret_after_configure(caplog):
    configure_logging("info", secrets=[])
    register_secret("late_added_pw")
    log = logging.getLogger("test")
    with caplog.at_level(logging.INFO):
        log.info("user pw=late_added_pw posted")
    assert "late_added_pw" not in caplog.text


def test_short_secrets_are_ignored():
    configure_logging("info", secrets=["a", "ab"])
    log = logging.getLogger("test")
    log.info("the cat sat on the mat")
