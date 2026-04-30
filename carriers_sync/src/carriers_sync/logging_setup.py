"""Root-logger configuration plus a LogRecord factory wrapper that scrubs
configured secrets from any log record's rendered message.

HA's options form lets users pick log levels using HA's vocabulary
(trace/debug/info/notice/warning/error/fatal). We map these to Python's.

We use setLogRecordFactory rather than a logging.Filter because filters on
loggers don't apply to records propagated from descendant loggers, and
filters on handlers don't apply to test/3rd-party capture handlers (e.g.
pytest's caplog). The factory hook fires once per record at creation time,
so redaction is total.
"""

from __future__ import annotations

import logging
from typing import Any

_HA_TO_PY_LEVEL = {
    "trace": logging.DEBUG,
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "notice": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
    "fatal": logging.CRITICAL,
}

_SECRETS: set[str] = set()
_FACTORY_INSTALLED = False
_DEFAULT_FACTORY = logging.getLogRecordFactory()


def _redacting_factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
    record = _DEFAULT_FACTORY(*args, **kwargs)
    if not _SECRETS:
        return record
    rendered = record.getMessage()
    redacted = rendered
    for s in _SECRETS:
        if s in redacted:
            redacted = redacted.replace(s, "***")
    if redacted != rendered:
        record.msg = redacted
        record.args = ()
    return record


def configure_logging(level: str, secrets: list[str]) -> None:
    """Configure root logger from an HA-vocabulary level + a list of secrets to redact."""
    global _FACTORY_INSTALLED
    _SECRETS.clear()
    for s in secrets:
        _add_secret(s)

    if not _FACTORY_INSTALLED:
        logging.setLogRecordFactory(_redacting_factory)
        _FACTORY_INSTALLED = True

    py_level = _HA_TO_PY_LEVEL.get(level.lower(), logging.INFO)
    root = logging.getLogger()
    # Only remove handlers we previously installed; leave third-party
    # handlers (e.g. pytest's caplog) alone.
    for h in list(root.handlers):
        if getattr(h, "_carriers_sync_owned", False):
            root.removeHandler(h)
    handler = logging.StreamHandler()
    handler._carriers_sync_owned = True  # type: ignore[attr-defined]
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    root.addHandler(handler)
    root.setLevel(py_level)


def register_secret(secret: str) -> None:
    """Register an additional secret to redact at runtime."""
    _add_secret(secret)


def _add_secret(secret: str) -> None:
    if len(secret) >= 3:
        _SECRETS.add(secret)
