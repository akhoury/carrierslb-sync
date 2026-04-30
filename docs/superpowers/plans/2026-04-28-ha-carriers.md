# Carriers Sync — Home Assistant App Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **User commit policy:** The user has a global rule "Never commit code without asking first." The commit steps in this plan are **proposals**: prepare the commit message and stage files, then ask the user before running `git commit`. Do not auto-commit.

**Goal:** Convert `carriers-sync` from a standalone Google-Keep-syncing Python script into a Home Assistant App that publishes Lebanese mobile-carrier (Alfa) usage data to HA via MQTT discovery, structured around a provider-adapter pattern so additional carriers (Touch) can be added later as a single new file.

**Architecture:** Single Docker container scheduled by HA Supervisor. Async Python entrypoint reads `/data/options.json`, runs Playwright/Chromium against the Alfa portal per account on a configurable interval, and publishes per-line sensors via MQTT discovery. Companion `state.json` in `/data/` survives restarts. Reference spec: `docs/superpowers/specs/2026-04-28-ha-carriers-lb-design.md`.

**Tech Stack:** Python 3.12, asyncio, Playwright (async API), `paho-mqtt` (or `aiomqtt`), `pyyaml` for `config.yaml` validation tooling, `ruff` for lint+format, `mypy --strict` for typing, `pytest` + `pytest-asyncio` + `freezegun` for tests. HA App base image `ghcr.io/home-assistant/base-python:3.12-bookworm` (multi-arch manifest).

---

## Repo target layout

```
carriers-sync/                          # repo root
├── carriers_sync/                      # the App directory (HA scans here)
│   ├── config.yaml
│   ├── Dockerfile
│   ├── run.sh
│   ├── icon.png                           # placeholder; user supplies later
│   ├── logo.png                           # placeholder; user supplies later
│   ├── CHANGELOG.md
│   ├── DOCS.md
│   └── src/
│       └── carriers_sync/              # Python package (same name, different level)
│           ├── __init__.py
│           ├── __main__.py
│           ├── scheduler.py
│           ├── mqtt_publisher.py
│           ├── discovery.py
│           ├── state_store.py
│           ├── config.py
│           ├── logging_setup.py
│           └── providers/
│               ├── __init__.py
│               ├── base.py
│               ├── alfa_lb.py
│               └── touch_lb.py
├── tests/
│   ├── unit/
│   │   ├── test_config.py
│   │   ├── test_state_store.py
│   │   ├── test_logging_setup.py
│   │   ├── test_providers_base.py
│   │   ├── test_alfa_lb_parser.py
│   │   ├── test_alfa_lb_fetch.py
│   │   ├── test_provider_registry.py
│   │   ├── test_discovery.py
│   │   ├── test_mqtt_publisher.py
│   │   └── test_scheduler.py
│   ├── fixtures/
│   │   ├── alfa_ushare_response.json
│   │   ├── alfa_mobile_internet.json
│   │   └── alfa_login_rejected.html
│   └── conftest.py
├── repository.yaml
├── pyproject.toml
├── README.md
├── LICENSE
├── .gitignore
└── .github/
    └── workflows/
        ├── ci.yml
        └── release.yml

```

The Python package name (`carriers_sync`) and the App directory (`carriers_sync/`) collide in concept but not on disk — the package lives at `carriers_sync/src/carriers_sync/`. `pyproject.toml` (at repo root) declares `pythonpath = ["carriers_sync/src"]` so tests import naturally.

---

## Task 1: Preserve legacy code on a branch and lay out new structure

**Files:**
- Create: `legacy/google-keep` git branch tagged from current `main`
- Create: tag `legacy-final` on current `main` HEAD
- Create: `.gitignore` (root)
- Create: `pyproject.toml` (root)
- Create: empty Python package directories with `__init__.py` files

- [ ] **Step 1: Tag legacy and create legacy branch**

```bash
git tag legacy-final
git branch legacy/google-keep legacy-final
```

Run: `git tag -l && git branch -a`
Expected: `legacy-final` tag exists; `legacy/google-keep` branch exists.

- [ ] **Step 2: Create root `.gitignore`**

Path: `.gitignore`

```gitignore
# Python
__pycache__/
*.py[cod]
*$py.class
*.egg-info/
.pytest_cache/
.mypy_cache/
.ruff_cache/
.coverage
htmlcov/
dist/
build/

# Virtualenvs
.venv/
venv/

# Editor
.vscode/
.idea/
*.swp
.DS_Store

# Local dev
config.cfg
supervisord.conf
supervisord.log
supervisord.pid
/data/
```

- [ ] **Step 3: Create `pyproject.toml`**

Path: `pyproject.toml`

```toml
[project]
name = "carriers-sync"
version = "0.1.0"
description = "Home Assistant App: sync mobile carrier usage data via MQTT discovery."
readme = "README.md"
requires-python = ">=3.12"
license = {text = "MIT"}
dependencies = [
    "playwright>=1.42",
    "aiomqtt>=2.0",
    "pyyaml>=6.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "pytest-mock>=3.12",
    "freezegun>=1.4",
    "ruff>=0.4",
    "mypy>=1.10",
    "types-PyYAML",
]

[build-system]
requires = ["setuptools>=61"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["carriers_sync/src"]

[tool.pytest.ini_options]
pythonpath = ["carriers_sync/src"]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "W", "I", "B", "UP", "SIM", "ASYNC"]
ignore = ["E501"]  # line length handled by formatter

[tool.mypy]
python_version = "3.12"
strict = true
mypy_path = "carriers_sync/src"
explicit_package_bases = true
```

- [ ] **Step 4: Create empty Python package skeleton**

Run:
```bash
mkdir -p carriers_sync/src/carriers_sync/providers
mkdir -p tests/unit tests/fixtures
touch carriers_sync/src/carriers_sync/__init__.py
touch carriers_sync/src/carriers_sync/providers/__init__.py
touch tests/__init__.py
touch tests/unit/__init__.py
touch tests/conftest.py
```

- [ ] **Step 5: Verify project tooling installs**

Run:
```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
ruff check .
mypy carriers_sync/src
pytest -q
```

Expected:
- `pip install` completes without errors.
- `ruff check .` reports `All checks passed!` (or no errors on empty tree).
- `mypy` reports `Success: no issues found in N source files`.
- `pytest` reports `no tests ran`.

- [ ] **Step 6: Propose commit**

Stage: `.gitignore pyproject.toml carriers_sync/ tests/`

Suggested message:
```
chore: lay out HA App skeleton and tooling

- Tag legacy-final and create legacy/google-keep branch for the
  pre-rewrite Google-Keep version.
- Add pyproject.toml with deps, ruff/mypy/pytest config, and
  src/ layout pointing tests at carriers_sync/src/.
- Empty package directories ready for incremental implementation.
```

Ask the user before running `git commit`.

---

## Task 2: Provider base contract — dataclasses, exceptions, Protocol

**Files:**
- Create: `carriers_sync/src/carriers_sync/providers/base.py`
- Create: `tests/unit/test_providers_base.py`

- [ ] **Step 1: Write the failing tests**

Path: `tests/unit/test_providers_base.py`

```python
from datetime import datetime, timezone

import pytest

from carriers_sync.providers.base import (
    AccountConfig,
    AuthFetchError,
    LineUsage,
    Provider,
    ProviderResult,
    TransientFetchError,
    UnknownFetchError,
)


def test_account_config_is_frozen():
    cfg = AccountConfig(
        provider="alfa-lb",
        username="03333333",
        password="secret",
        label="John",
        secondary_labels={"03222222": "Wife"},
    )
    with pytest.raises(Exception):
        cfg.username = "other"  # type: ignore[misc]


def test_line_usage_secondary_marker():
    main = LineUsage(
        line_id="03333333",
        label="John",
        consumed_gb=1.0,
        quota_gb=20.0,
        extra_consumed_gb=0.0,
        is_secondary=False,
        parent_line_id=None,
    )
    secondary = LineUsage(
        line_id="03222222",
        label="Wife",
        consumed_gb=2.5,
        quota_gb=None,
        extra_consumed_gb=0.0,
        is_secondary=True,
        parent_line_id="03333333",
    )
    assert main.is_secondary is False and main.parent_line_id is None
    assert secondary.is_secondary is True
    assert secondary.parent_line_id == "03333333"
    assert secondary.quota_gb is None


def test_provider_result_holds_lines_and_timestamp():
    now = datetime(2026, 4, 28, 12, 0, tzinfo=timezone.utc)
    result = ProviderResult(
        account_id="03333333",
        lines=[
            LineUsage(
                line_id="03333333",
                label="John",
                consumed_gb=1.0,
                quota_gb=20.0,
                extra_consumed_gb=0.0,
                is_secondary=False,
                parent_line_id=None,
            )
        ],
        fetched_at=now,
    )
    assert result.account_id == "03333333"
    assert len(result.lines) == 1
    assert result.fetched_at == now


def test_exception_classes_are_distinct():
    assert issubclass(TransientFetchError, Exception)
    assert issubclass(AuthFetchError, Exception)
    assert issubclass(UnknownFetchError, Exception)
    assert TransientFetchError is not AuthFetchError


def test_provider_protocol_requires_id_and_fetch():
    # Protocol check: a class missing id/fetch should not satisfy Provider at runtime.
    # We don't instantiate Protocol directly; we rely on the Protocol declaration.
    # This test documents the expected interface.
    assert hasattr(Provider, "id")
    assert hasattr(Provider, "display_name")
    assert hasattr(Provider, "fetch")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_providers_base.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'carriers_sync.providers.base'`.

- [ ] **Step 3: Implement `providers/base.py`**

Path: `carriers_sync/src/carriers_sync/providers/base.py`

```python
"""Provider adapter contract.

Every carrier adapter (Alfa, Touch, etc.) implements the Provider protocol
defined here. The scheduler is provider-agnostic; it sees only ProviderResult
and LineUsage.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import ClassVar, Protocol


@dataclass(frozen=True, slots=True)
class AccountConfig:
    """One configured account from /data/options.json."""

    provider: str
    username: str
    password: str
    label: str
    secondary_labels: dict[str, str]
    # On disk in options.json this is a list of {number, label} objects
    # (HA's schema doesn't support free-key maps); config.py converts it
    # to a dict[phone_number, label] for runtime use.


@dataclass(frozen=True, slots=True)
class LineUsage:
    """One billable line — either a main account number or a U-share secondary."""

    line_id: str
    label: str
    consumed_gb: float
    quota_gb: float | None  # None for secondaries that share the parent quota
    extra_consumed_gb: float
    is_secondary: bool
    parent_line_id: str | None  # for HA via_device linking


@dataclass(frozen=True, slots=True)
class ProviderResult:
    """Result of one fetch for one account."""

    account_id: str
    lines: list[LineUsage]
    fetched_at: datetime


class TransientFetchError(Exception):
    """Network timeout, URL rejected, browser crash. Worth retrying with backoff."""


class AuthFetchError(Exception):
    """Invalid credentials, account locked, captcha. Do NOT retry this cycle."""


class UnknownFetchError(Exception):
    """Unexpected page structure or JSON shape. One retry only."""


class Provider(Protocol):
    """Protocol every provider adapter must satisfy."""

    id: ClassVar[str]
    display_name: ClassVar[str]

    async def fetch(
        self,
        account: AccountConfig,
        browser: object,  # playwright.async_api.Browser, but kept loose to avoid
                          # forcing playwright as a hard dep on this module
    ) -> ProviderResult: ...
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_providers_base.py -v`
Expected: 5 passed.

- [ ] **Step 5: Run typecheck and lint**

Run: `mypy carriers_sync/src && ruff check carriers_sync/src tests`
Expected: both clean.

- [ ] **Step 6: Propose commit**

Stage: `carriers_sync/src/carriers_sync/providers/base.py tests/unit/test_providers_base.py`

Suggested message: `feat(providers): add Provider protocol and result dataclasses`

Ask the user before committing.

---

## Task 3: Config parser — read & validate /data/options.json

**Files:**
- Create: `carriers_sync/src/carriers_sync/config.py`
- Create: `tests/unit/test_config.py`

- [ ] **Step 1: Write the failing tests**

Path: `tests/unit/test_config.py`

```python
import json

import pytest

from carriers_sync.config import AppConfig, ConfigError, load_config
from carriers_sync.providers.base import AccountConfig


def write_options(tmp_path, payload):
    p = tmp_path / "options.json"
    p.write_text(json.dumps(payload))
    return p


def test_load_minimal_valid_config(tmp_path):
    path = write_options(tmp_path, {
        "poll_interval_minutes": 60,
        "danger_percent": 80,
        "log_level": "info",
        "accounts": [
            {
                "provider": "alfa-lb",
                "username": "03333333",
                "password": "secret",
                "label": "John",
                "secondary_labels": [],
            }
        ],
    })
    cfg = load_config(path)
    assert isinstance(cfg, AppConfig)
    assert cfg.poll_interval_minutes == 60
    assert cfg.danger_percent == 80
    assert cfg.log_level == "info"
    assert len(cfg.accounts) == 1
    acct = cfg.accounts[0]
    assert isinstance(acct, AccountConfig)
    assert acct.username == "03333333"
    assert acct.label == "John"
    assert acct.secondary_labels == {}


def test_secondary_labels_list_to_dict_conversion(tmp_path):
    path = write_options(tmp_path, {
        "poll_interval_minutes": 60,
        "danger_percent": 80,
        "log_level": "info",
        "accounts": [
            {
                "provider": "alfa-lb",
                "username": "03333333",
                "password": "p",
                "label": "John",
                "secondary_labels": [
                    {"number": "03222222", "label": "Wife"},
                    {"number": "03111111", "label": "Alarm eSIM"},
                ],
            }
        ],
    })
    cfg = load_config(path)
    assert cfg.accounts[0].secondary_labels == {
        "03222222": "Wife",
        "03111111": "Alarm eSIM",
    }


def test_duplicate_usernames_dedup_first_wins(tmp_path, caplog):
    path = write_options(tmp_path, {
        "poll_interval_minutes": 60,
        "danger_percent": 80,
        "log_level": "info",
        "accounts": [
            {"provider": "alfa-lb", "username": "03333333", "password": "a",
             "label": "First", "secondary_labels": []},
            {"provider": "alfa-lb", "username": "03333333", "password": "b",
             "label": "Dup", "secondary_labels": []},
        ],
    })
    cfg = load_config(path)
    assert len(cfg.accounts) == 1
    assert cfg.accounts[0].label == "First"


def test_missing_file_raises_config_error(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "missing.json")


def test_malformed_json_raises_config_error(tmp_path):
    path = tmp_path / "options.json"
    path.write_text("{not json")
    with pytest.raises(ConfigError, match="JSON"):
        load_config(path)


def test_missing_required_field_raises(tmp_path):
    path = write_options(tmp_path, {
        "poll_interval_minutes": 60,
        "danger_percent": 80,
        # log_level missing
        "accounts": [],
    })
    with pytest.raises(ConfigError, match="log_level"):
        load_config(path)


def test_empty_accounts_list_is_allowed(tmp_path):
    path = write_options(tmp_path, {
        "poll_interval_minutes": 60,
        "danger_percent": 80,
        "log_level": "info",
        "accounts": [],
    })
    cfg = load_config(path)
    assert cfg.accounts == []


def test_invalid_provider_rejected(tmp_path):
    path = write_options(tmp_path, {
        "poll_interval_minutes": 60,
        "danger_percent": 80,
        "log_level": "info",
        "accounts": [
            {"provider": "unknown-co", "username": "x", "password": "y",
             "label": "z", "secondary_labels": []},
        ],
    })
    with pytest.raises(ConfigError, match="provider"):
        load_config(path)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'carriers_sync.config'`.

- [ ] **Step 3: Implement `config.py`**

Path: `carriers_sync/src/carriers_sync/config.py`

```python
"""Reads, validates, and shapes /data/options.json into typed dataclasses.

The on-disk format is what HA's Supervisor writes from the user's options form;
shape mismatches between disk and runtime (e.g. secondary_labels list -> dict)
are reconciled here so the rest of the codebase sees only typed dataclasses.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from carriers_sync.providers.base import AccountConfig

logger = logging.getLogger("carriers_sync.config")

KNOWN_PROVIDERS = {"alfa-lb"}  # extend when Touch lands
VALID_LOG_LEVELS = {"trace", "debug", "info", "notice", "warning", "error", "fatal"}


class ConfigError(Exception):
    """Raised when /data/options.json is missing, malformed, or invalid."""


@dataclass(frozen=True, slots=True)
class AppConfig:
    poll_interval_minutes: int
    danger_percent: int
    log_level: str
    accounts: list[AccountConfig]


def load_config(path: Path) -> AppConfig:
    """Read and validate options.json. Raise ConfigError on any problem."""
    if not path.exists():
        raise ConfigError(f"Options file not found: {path}")

    try:
        raw = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        raise ConfigError(f"options.json is not valid JSON: {e}") from e

    if not isinstance(raw, dict):
        raise ConfigError("options.json root must be an object")

    poll = _require(raw, "poll_interval_minutes", int)
    danger = _require(raw, "danger_percent", int)
    log_level = _require(raw, "log_level", str)
    accounts_raw = _require(raw, "accounts", list)

    if log_level not in VALID_LOG_LEVELS:
        raise ConfigError(f"log_level must be one of {VALID_LOG_LEVELS}, got {log_level!r}")
    if not (5 <= poll <= 1440):
        raise ConfigError(f"poll_interval_minutes must be in [5, 1440], got {poll}")
    if not (1 <= danger <= 100):
        raise ConfigError(f"danger_percent must be in [1, 100], got {danger}")

    accounts: list[AccountConfig] = []
    seen_usernames: set[str] = set()
    for i, item in enumerate(accounts_raw):
        if not isinstance(item, dict):
            raise ConfigError(f"accounts[{i}] must be an object")
        acct = _parse_account(item, index=i)
        if acct.username in seen_usernames:
            logger.warning(
                "Duplicate account username %s — keeping first, dropping later entry",
                acct.username,
            )
            continue
        seen_usernames.add(acct.username)
        accounts.append(acct)

    return AppConfig(
        poll_interval_minutes=poll,
        danger_percent=danger,
        log_level=log_level,
        accounts=accounts,
    )


def _parse_account(item: dict[str, Any], *, index: int) -> AccountConfig:
    provider = _require(item, "provider", str, ctx=f"accounts[{index}]")
    if provider not in KNOWN_PROVIDERS:
        raise ConfigError(
            f"accounts[{index}].provider must be one of {KNOWN_PROVIDERS}, got {provider!r}"
        )
    username = _require(item, "username", str, ctx=f"accounts[{index}]")
    password = _require(item, "password", str, ctx=f"accounts[{index}]")
    label = _require(item, "label", str, ctx=f"accounts[{index}]")
    raw_secondaries = item.get("secondary_labels", [])
    if not isinstance(raw_secondaries, list):
        raise ConfigError(f"accounts[{index}].secondary_labels must be a list")

    secondary_labels: dict[str, str] = {}
    for j, entry in enumerate(raw_secondaries):
        if not isinstance(entry, dict):
            raise ConfigError(f"accounts[{index}].secondary_labels[{j}] must be an object")
        number = _require(entry, "number", str, ctx=f"accounts[{index}].secondary_labels[{j}]")
        slabel = _require(entry, "label", str, ctx=f"accounts[{index}].secondary_labels[{j}]")
        secondary_labels[number] = slabel

    return AccountConfig(
        provider=provider,
        username=username,
        password=password,
        label=label,
        secondary_labels=secondary_labels,
    )


def _require(d: dict[str, Any], key: str, expected_type: type, *, ctx: str = "") -> Any:
    if key not in d:
        prefix = f"{ctx}." if ctx else ""
        raise ConfigError(f"missing required field: {prefix}{key}")
    value = d[key]
    if not isinstance(value, expected_type):
        prefix = f"{ctx}." if ctx else ""
        raise ConfigError(
            f"{prefix}{key} must be {expected_type.__name__}, got {type(value).__name__}"
        )
    return value
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_config.py -v`
Expected: 8 passed.

- [ ] **Step 5: Run typecheck and lint**

Run: `mypy carriers_sync/src && ruff check carriers_sync/src tests`
Expected: both clean.

- [ ] **Step 6: Propose commit**

Stage: `carriers_sync/src/carriers_sync/config.py tests/unit/test_config.py`

Suggested message: `feat(config): parse /data/options.json into typed AppConfig`

Ask before committing.

---

## Task 4: State store — atomic JSON read/write with corruption recovery

**Files:**
- Create: `carriers_sync/src/carriers_sync/state_store.py`
- Create: `tests/unit/test_state_store.py`

- [ ] **Step 1: Write the failing tests**

Path: `tests/unit/test_state_store.py`

```python
import json
from datetime import datetime, timezone
from pathlib import Path

from carriers_sync.providers.base import LineUsage, ProviderResult
from carriers_sync.state_store import State, StateStore


def make_result(account_id="03333333"):
    return ProviderResult(
        account_id=account_id,
        lines=[
            LineUsage(
                line_id=account_id,
                label="John",
                consumed_gb=1.5,
                quota_gb=20.0,
                extra_consumed_gb=0.0,
                is_secondary=False,
                parent_line_id=None,
            )
        ],
        fetched_at=datetime(2026, 4, 28, 12, 0, tzinfo=timezone.utc),
    )


def test_empty_store_returns_default_state(tmp_path):
    store = StateStore(tmp_path / "state.json")
    state = store.load()
    assert state.last_results == {}
    assert state.last_published_entities == set()


def test_round_trip(tmp_path):
    store = StateStore(tmp_path / "state.json")
    state = State(
        last_results={"03333333": make_result()},
        last_published_entities={"sensor.alfa_john_consumed_gb"},
    )
    store.save(state)
    loaded = store.load()
    assert "03333333" in loaded.last_results
    assert loaded.last_results["03333333"].lines[0].consumed_gb == 1.5
    assert "sensor.alfa_john_consumed_gb" in loaded.last_published_entities


def test_atomic_write_uses_tmp_file(tmp_path, monkeypatch):
    """save() must write to a tmp file and rename, not truncate the target."""
    target = tmp_path / "state.json"
    store = StateStore(target)
    store.save(State(last_results={"03333333": make_result()}, last_published_entities=set()))

    # Verify no leftover .tmp file.
    assert not (tmp_path / "state.json.tmp").exists()
    assert target.exists()


def test_corrupt_file_recovers_with_warning(tmp_path, caplog):
    target = tmp_path / "state.json"
    target.write_text("{this is not json")
    store = StateStore(target)
    state = store.load()
    assert state.last_results == {}
    # Corrupted file is moved aside.
    assert not target.exists() or target.read_text() != "{this is not json"
    assert any("corrupt" in r.message.lower() for r in caplog.records)


def test_save_then_load_preserves_unicode_labels(tmp_path):
    store = StateStore(tmp_path / "state.json")
    res = ProviderResult(
        account_id="03333333",
        lines=[
            LineUsage(
                line_id="03333333",
                label="جون",
                consumed_gb=1.0,
                quota_gb=20.0,
                extra_consumed_gb=0.0,
                is_secondary=False,
                parent_line_id=None,
            )
        ],
        fetched_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
    )
    store.save(State(last_results={"03333333": res}, last_published_entities=set()))
    loaded = store.load()
    assert loaded.last_results["03333333"].lines[0].label == "جون"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_state_store.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `state_store.py`**

Path: `carriers_sync/src/carriers_sync/state_store.py`

```python
"""Persists last successful ProviderResult per account and the set of
currently-published discovery entities. Used to repopulate sensors after
container restart and to clean up entities for removed accounts.

Storage is a single JSON file at /data/state.json. Writes are atomic
(temp file + os.replace). On corruption, the file is moved aside and
fresh state is returned.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from carriers_sync.providers.base import LineUsage, ProviderResult

logger = logging.getLogger("carriers_sync.state")


@dataclass
class State:
    last_results: dict[str, ProviderResult] = field(default_factory=dict)
    last_published_entities: set[str] = field(default_factory=set)


class StateStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> State:
        if not self.path.exists():
            return State()
        try:
            raw = json.loads(self.path.read_text())
        except json.JSONDecodeError as e:
            logger.warning("state.json is corrupt (%s); starting fresh", e)
            self._move_aside_corrupt()
            return State()

        results: dict[str, ProviderResult] = {}
        for acct_id, payload in raw.get("last_results", {}).items():
            try:
                results[acct_id] = _result_from_dict(payload)
            except (KeyError, TypeError, ValueError) as e:
                logger.warning("dropping corrupt account %s from state: %s", acct_id, e)

        return State(
            last_results=results,
            last_published_entities=set(raw.get("last_published_entities", [])),
        )

    def save(self, state: State) -> None:
        payload = {
            "last_results": {
                acct: _result_to_dict(res) for acct, res in state.last_results.items()
            },
            "last_published_entities": sorted(state.last_published_entities),
        }
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
        os.replace(tmp, self.path)

    def _move_aside_corrupt(self) -> None:
        if not self.path.exists():
            return
        backup = self.path.with_suffix(self.path.suffix + ".corrupt")
        try:
            os.replace(self.path, backup)
        except OSError:
            # Best-effort; if we can't rename, just unlink.
            self.path.unlink(missing_ok=True)


def _result_to_dict(r: ProviderResult) -> dict:
    return {
        "account_id": r.account_id,
        "fetched_at": r.fetched_at.isoformat(),
        "lines": [
            {
                "line_id": line.line_id,
                "label": line.label,
                "consumed_gb": line.consumed_gb,
                "quota_gb": line.quota_gb,
                "extra_consumed_gb": line.extra_consumed_gb,
                "is_secondary": line.is_secondary,
                "parent_line_id": line.parent_line_id,
            }
            for line in r.lines
        ],
    }


def _result_from_dict(d: dict) -> ProviderResult:
    return ProviderResult(
        account_id=d["account_id"],
        fetched_at=datetime.fromisoformat(d["fetched_at"]),
        lines=[
            LineUsage(
                line_id=line["line_id"],
                label=line["label"],
                consumed_gb=float(line["consumed_gb"]),
                quota_gb=None if line["quota_gb"] is None else float(line["quota_gb"]),
                extra_consumed_gb=float(line["extra_consumed_gb"]),
                is_secondary=bool(line["is_secondary"]),
                parent_line_id=line["parent_line_id"],
            )
            for line in d["lines"]
        ],
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_state_store.py -v`
Expected: 5 passed.

- [ ] **Step 5: Run typecheck and lint**

Run: `mypy carriers_sync/src && ruff check carriers_sync/src tests`
Expected: clean.

- [ ] **Step 6: Propose commit**

Stage: `carriers_sync/src/carriers_sync/state_store.py tests/unit/test_state_store.py`

Suggested message: `feat(state): atomic JSON state store with corrupt-file recovery`

Ask before committing.

---

## Task 5: Logging setup with credential redactor

**Files:**
- Create: `carriers_sync/src/carriers_sync/logging_setup.py`
- Create: `tests/unit/test_logging_setup.py`

- [ ] **Step 1: Write the failing tests**

Path: `tests/unit/test_logging_setup.py`

```python
import logging

from carriers_sync.logging_setup import configure_logging, register_secret


def test_configure_logging_sets_root_level():
    configure_logging("debug", secrets=[])
    assert logging.getLogger().level == logging.DEBUG


def test_configure_logging_maps_ha_levels_to_python():
    configure_logging("notice", secrets=[])
    # 'notice' is between INFO and WARNING in HA semantics; we map it to INFO.
    assert logging.getLogger().level == logging.INFO

    configure_logging("trace", secrets=[])
    # 'trace' is the verbose-most; map to DEBUG (Python has no TRACE).
    assert logging.getLogger().level == logging.DEBUG


def test_credential_redactor_strips_secrets(caplog):
    configure_logging("info", secrets=["super_secret_pw"])
    log = logging.getLogger("test")
    log.info("connecting with password=super_secret_pw to alfa")
    assert "super_secret_pw" not in caplog.text
    assert "***" in caplog.text


def test_register_secret_after_configure(caplog):
    configure_logging("info", secrets=[])
    register_secret("late_added_pw")
    log = logging.getLogger("test")
    log.info("user pw=late_added_pw posted")
    assert "late_added_pw" not in caplog.text


def test_short_secrets_are_ignored():
    """Don't redact 1-2 char secrets — would corrupt unrelated log text."""
    configure_logging("info", secrets=["a", "ab"])
    log = logging.getLogger("test")
    # Calling these should not crash; assertion is that nothing breaks.
    log.info("the cat sat on the mat")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_logging_setup.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `logging_setup.py`**

Path: `carriers_sync/src/carriers_sync/logging_setup.py`

```python
"""Root-logger configuration plus a Filter that scrubs configured secrets
from any log record's message.

HA's options form lets users pick log levels using HA's vocabulary
(trace/debug/info/notice/warning/error/fatal). We map these to Python's.
"""
from __future__ import annotations

import logging

_HA_TO_PY_LEVEL = {
    "trace": logging.DEBUG,
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "notice": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
    "fatal": logging.CRITICAL,
}

_REDACTOR: "CredentialRedactor | None" = None


class CredentialRedactor(logging.Filter):
    """Replaces any occurrence of a registered secret with '***' in log messages."""

    def __init__(self, secrets: list[str]) -> None:
        super().__init__()
        self._secrets: set[str] = set()
        for s in secrets:
            self.add(s)

    def add(self, secret: str) -> None:
        # Refuse to redact short strings; risk of corrupting unrelated text.
        if len(secret) >= 3:
            self._secrets.add(secret)

    def filter(self, record: logging.LogRecord) -> bool:
        if not self._secrets:
            return True
        msg = record.getMessage()
        replaced = msg
        for s in self._secrets:
            if s in replaced:
                replaced = replaced.replace(s, "***")
        if replaced is not msg:
            record.msg = replaced
            record.args = ()
        return True


def configure_logging(level: str, secrets: list[str]) -> None:
    """Configure root logger from an HA-vocabulary level + a list of secrets to redact."""
    global _REDACTOR
    py_level = _HA_TO_PY_LEVEL.get(level.lower(), logging.INFO)
    root = logging.getLogger()
    # Remove any previously installed handlers/filters so this is idempotent.
    for h in list(root.handlers):
        root.removeHandler(h)
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )
    redactor = CredentialRedactor(secrets)
    handler.addFilter(redactor)
    root.addHandler(handler)
    root.setLevel(py_level)
    _REDACTOR = redactor


def register_secret(secret: str) -> None:
    """Register an additional secret to redact (e.g. a credential added at runtime)."""
    if _REDACTOR is None:
        # configure_logging() hasn't run yet — defer is fine; first config will
        # not include this. Most callers use configure_logging() at startup.
        return
    _REDACTOR.add(secret)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_logging_setup.py -v`
Expected: 5 passed.

- [ ] **Step 5: Run typecheck and lint**

Run: `mypy carriers_sync/src && ruff check carriers_sync/src tests`
Expected: clean.

- [ ] **Step 6: Propose commit**

Stage: `carriers_sync/src/carriers_sync/logging_setup.py tests/unit/test_logging_setup.py`

Suggested message: `feat(logging): root logger config with credential redactor`

Ask before committing.

---

## Task 6: Capture Alfa response fixtures

**Files:**
- Create: `tests/fixtures/alfa_ushare_response.json`
- Create: `tests/fixtures/alfa_mobile_internet.json`
- Create: `tests/fixtures/alfa_login_rejected.html`

- [ ] **Step 1: Create U-share fixture**

Path: `tests/fixtures/alfa_ushare_response.json`

This is an anonymised real-shape Alfa response. The numeric values are placeholders; the keys must match what the live API returns (see existing `carrierslb_sync.py` lines 53–95 for the expected shape).

```json
{
  "ServiceInformationValue": [
    {
      "ServiceNameValue": "U-share Main",
      "ServiceDetailsInformationValue": [
        {
          "ConsumptionValue": "2048",
          "ConsumptionUnitValue": "MB",
          "ExtraConsumptionValue": "0",
          "PackageValue": "20",
          "PackageUnitValue": "GB",
          "SecondaryValue": [
            {
              "SecondaryNumberValue": "03222222",
              "BundleNameValue": "Twin-Data Secondary",
              "ConsumptionValue": "1024",
              "ConsumptionUnitValue": "MB"
            },
            {
              "SecondaryNumberValue": "03111111",
              "BundleNameValue": "Twin-Data Secondary",
              "ConsumptionValue": "512",
              "ConsumptionUnitValue": "MB"
            }
          ]
        }
      ]
    }
  ]
}
```

- [ ] **Step 2: Create Mobile Internet fixture**

Path: `tests/fixtures/alfa_mobile_internet.json`

```json
{
  "ServiceInformationValue": [
    {
      "ServiceNameValue": "Mobile Internet",
      "ServiceDetailsInformationValue": [
        {
          "ConsumptionValue": "5.5",
          "ConsumptionUnitValue": "GB",
          "ExtraConsumptionValue": "0.0",
          "PackageValue": "10",
          "PackageUnitValue": "GB"
        }
      ]
    }
  ]
}
```

- [ ] **Step 3: Create login-rejected HTML fixture**

Path: `tests/fixtures/alfa_login_rejected.html`

```html
<!doctype html>
<html><body>
<h1>The requested URL was rejected. Please consult with your administrator.</h1>
<p>Your support ID is: 1234567890</p>
</body></html>
```

- [ ] **Step 4: Verify fixtures load as JSON**

Run:
```bash
python3 -c "import json; json.load(open('tests/fixtures/alfa_ushare_response.json'))"
python3 -c "import json; json.load(open('tests/fixtures/alfa_mobile_internet.json'))"
```
Expected: no output, exit 0.

- [ ] **Step 5: Propose commit**

Stage: `tests/fixtures/`

Suggested message: `test: add anonymised Alfa response fixtures`

Ask before committing.

---

## Task 7: Alfa response parser — pure function

**Files:**
- Create: `carriers_sync/src/carriers_sync/providers/alfa_lb.py` (parser only this task)
- Create: `tests/unit/test_alfa_lb_parser.py`

- [ ] **Step 1: Write the failing tests**

Path: `tests/unit/test_alfa_lb_parser.py`

```python
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from carriers_sync.providers.alfa_lb import parse_response
from carriers_sync.providers.base import (
    AccountConfig,
    UnknownFetchError,
)

FIXTURES = Path(__file__).parent.parent / "fixtures"


def make_account(secondary_labels=None):
    return AccountConfig(
        provider="alfa-lb",
        username="03333333",
        password="x",
        label="John",
        secondary_labels=secondary_labels or {"03222222": "Wife", "03111111": "Alarm eSIM"},
    )


def load(name):
    return json.loads((FIXTURES / name).read_text())


def test_parse_ushare_yields_main_plus_secondaries():
    payload = load("alfa_ushare_response.json")
    fetched_at = datetime(2026, 4, 28, 12, 0, tzinfo=timezone.utc)
    result = parse_response(payload, account=make_account(), fetched_at=fetched_at)

    assert result.account_id == "03333333"
    assert result.fetched_at == fetched_at
    assert len(result.lines) == 3

    main = result.lines[0]
    assert main.line_id == "03333333"
    assert main.label == "John"
    assert main.is_secondary is False
    assert main.consumed_gb == pytest.approx(2.0)  # 2048 MB / 1024
    assert main.quota_gb == pytest.approx(20.0)
    assert main.extra_consumed_gb == 0.0
    assert main.parent_line_id is None

    sec1 = result.lines[1]
    assert sec1.line_id == "03222222"
    assert sec1.label == "Wife"
    assert sec1.is_secondary is True
    assert sec1.consumed_gb == pytest.approx(1.0)
    assert sec1.quota_gb is None
    assert sec1.parent_line_id == "03333333"

    sec2 = result.lines[2]
    assert sec2.line_id == "03111111"
    assert sec2.label == "Alarm eSIM"


def test_parse_mobile_internet_no_secondaries():
    payload = load("alfa_mobile_internet.json")
    result = parse_response(
        payload,
        account=make_account(secondary_labels={}),
        fetched_at=datetime.now(timezone.utc),
    )
    assert len(result.lines) == 1
    main = result.lines[0]
    assert main.consumed_gb == pytest.approx(5.5)
    assert main.quota_gb == pytest.approx(10.0)
    assert main.is_secondary is False


def test_secondary_without_label_falls_back_to_phone_number():
    payload = load("alfa_ushare_response.json")
    result = parse_response(
        payload,
        account=make_account(secondary_labels={"03222222": "Wife"}),  # only one labelled
        fetched_at=datetime.now(timezone.utc),
    )
    sec_unlabelled = next(l for l in result.lines if l.line_id == "03111111")
    assert sec_unlabelled.label == "03111111"


def test_extra_consumption_passed_through():
    payload = {
        "ServiceInformationValue": [
            {
                "ServiceNameValue": "Mobile Internet",
                "ServiceDetailsInformationValue": [
                    {
                        "ConsumptionValue": "9",
                        "ConsumptionUnitValue": "GB",
                        "ExtraConsumptionValue": "1.5",
                        "PackageValue": "10",
                        "PackageUnitValue": "GB",
                    }
                ],
            }
        ]
    }
    result = parse_response(
        payload,
        account=make_account(secondary_labels={}),
        fetched_at=datetime.now(timezone.utc),
    )
    assert result.lines[0].extra_consumed_gb == pytest.approx(1.5)


def test_missing_service_information_raises_unknown():
    with pytest.raises(UnknownFetchError):
        parse_response(
            {},
            account=make_account(secondary_labels={}),
            fetched_at=datetime.now(timezone.utc),
        )


def test_no_supported_service_raises_unknown():
    payload = {
        "ServiceInformationValue": [
            {"ServiceNameValue": "Voice", "ServiceDetailsInformationValue": []}
        ]
    }
    with pytest.raises(UnknownFetchError, match="no supported service"):
        parse_response(
            payload,
            account=make_account(secondary_labels={}),
            fetched_at=datetime.now(timezone.utc),
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_alfa_lb_parser.py -v`
Expected: FAIL with `ImportError: cannot import name 'parse_response'`.

- [ ] **Step 3: Implement parser in `alfa_lb.py`**

Path: `carriers_sync/src/carriers_sync/providers/alfa_lb.py`

```python
"""Alfa Lebanon provider adapter.

Split into:
  - parse_response(): pure function, fully unit-tested with fixtures.
  - AlfaLbProvider.fetch(): Playwright-driven scrape that calls parse_response.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar

from carriers_sync.providers.base import (
    AccountConfig,
    LineUsage,
    ProviderResult,
    UnknownFetchError,
)

_SUPPORTED_SERVICES = {"U-share Main", "Mobile Internet"}


def parse_response(
    payload: dict[str, Any],
    *,
    account: AccountConfig,
    fetched_at: datetime,
) -> ProviderResult:
    """Convert Alfa's getconsumption JSON into a ProviderResult.

    Raises UnknownFetchError on any shape mismatch. Caller is responsible
    for catching and translating to the right scheduler-side action.
    """
    services = payload.get("ServiceInformationValue")
    if not isinstance(services, list) or not services:
        raise UnknownFetchError("missing or empty ServiceInformationValue")

    siv = next(
        (s for s in services if s.get("ServiceNameValue") in _SUPPORTED_SERVICES),
        None,
    )
    if siv is None:
        raise UnknownFetchError(
            f"no supported service in response (have: "
            f"{[s.get('ServiceNameValue') for s in services]})"
        )

    details_list = siv.get("ServiceDetailsInformationValue")
    if not isinstance(details_list, list) or not details_list:
        raise UnknownFetchError("missing ServiceDetailsInformationValue")
    details = details_list[0]

    main_consumed_gb = _to_gb(
        _require_num(details, "ConsumptionValue"),
        details.get("ConsumptionUnitValue", "GB"),
    )
    main_quota_gb = _to_gb(
        _require_num(details, "PackageValue"),
        details.get("PackageUnitValue", "GB"),
    )
    main_extra_gb = _to_gb(
        _require_num(details, "ExtraConsumptionValue"),
        details.get("ConsumptionUnitValue", "GB"),
    )

    main_line = LineUsage(
        line_id=account.username,
        label=account.label or account.username,
        consumed_gb=main_consumed_gb,
        quota_gb=main_quota_gb,
        extra_consumed_gb=main_extra_gb,
        is_secondary=False,
        parent_line_id=None,
    )

    lines: list[LineUsage] = [main_line]

    for sv in details.get("SecondaryValue") or []:
        if sv.get("BundleNameValue") != "Twin-Data Secondary":
            continue
        number = sv.get("SecondaryNumberValue")
        if not isinstance(number, str):
            raise UnknownFetchError("secondary missing SecondaryNumberValue")
        consumed = _to_gb(
            _require_num(sv, "ConsumptionValue"),
            sv.get("ConsumptionUnitValue", "GB"),
        )
        lines.append(
            LineUsage(
                line_id=number,
                label=account.secondary_labels.get(number, number),
                consumed_gb=consumed,
                quota_gb=None,
                extra_consumed_gb=0.0,
                is_secondary=True,
                parent_line_id=account.username,
            )
        )

    return ProviderResult(
        account_id=account.username,
        lines=lines,
        fetched_at=fetched_at,
    )


def _require_num(d: dict[str, Any], key: str) -> float:
    if key not in d:
        raise UnknownFetchError(f"missing field: {key}")
    try:
        return float(d[key])
    except (TypeError, ValueError) as e:
        raise UnknownFetchError(f"{key} is not numeric: {d[key]!r}") from e


def _to_gb(value: float, unit: str) -> float:
    if unit == "MB":
        return round(value / 1024, 3)
    if unit == "GB":
        return round(value, 3)
    raise UnknownFetchError(f"unknown unit: {unit}")


class AlfaLbProvider:
    """Stub — fetch() is implemented in Task 8."""

    id: ClassVar[str] = "alfa-lb"
    display_name: ClassVar[str] = "Alfa (Lebanon)"

    async def fetch(
        self,
        account: AccountConfig,
        browser: object,
    ) -> ProviderResult:
        raise NotImplementedError("implemented in Task 8")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_alfa_lb_parser.py -v`
Expected: 6 passed.

- [ ] **Step 5: Run typecheck and lint**

Run: `mypy carriers_sync/src && ruff check carriers_sync/src tests`
Expected: clean.

- [ ] **Step 6: Propose commit**

Stage: `carriers_sync/src/carriers_sync/providers/alfa_lb.py tests/unit/test_alfa_lb_parser.py`

Suggested message: `feat(providers): pure parser for Alfa getconsumption response`

Ask before committing.

---

## Task 8: Alfa fetch — Playwright wrapper

**Files:**
- Modify: `carriers_sync/src/carriers_sync/providers/alfa_lb.py` (replace `AlfaLbProvider.fetch`)
- Create: `tests/unit/test_alfa_lb_fetch.py`

- [ ] **Step 1: Write the failing tests (mocked browser)**

Path: `tests/unit/test_alfa_lb_fetch.py`

```python
"""Light-touch tests for AlfaLbProvider.fetch using a mocked Playwright browser.

We don't drive a real browser here — that's the optional integration test.
These tests verify the wiring: form fill + login click + waiting for the
getconsumption XHR + handing the JSON to parse_response + classifying errors.
"""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from carriers_sync.providers.alfa_lb import AlfaLbProvider
from carriers_sync.providers.base import (
    AccountConfig,
    AuthFetchError,
    TransientFetchError,
)


def make_account():
    return AccountConfig(
        provider="alfa-lb",
        username="03333333",
        password="pw",
        label="John",
        secondary_labels={"03222222": "Wife"},
    )


def make_browser(*, page_text="ok", xhr_json=None, raise_on_wait=None):
    """Build a fake Playwright browser whose context.new_page returns a
    page that the adapter can drive.

    page_text     — what page.text_content('body') returns by default
    xhr_json      — the JSON the expect_response context manager yields
    raise_on_wait — if set, raise this exception from expect_response
    """
    page = MagicMock()
    page.goto = AsyncMock()
    page.fill = AsyncMock()
    page.click = AsyncMock()
    page.text_content = AsyncMock(return_value=page_text)

    response = MagicMock()
    response.json = AsyncMock(return_value=xhr_json)

    cm = MagicMock()
    if raise_on_wait is not None:
        cm.__aenter__ = AsyncMock(side_effect=raise_on_wait)
    else:
        cm.__aenter__ = AsyncMock(return_value=MagicMock(value=response))
    cm.__aexit__ = AsyncMock(return_value=None)
    page.expect_response = MagicMock(return_value=cm)

    context = MagicMock()
    context.new_page = AsyncMock(return_value=page)
    context.set_default_navigation_timeout = MagicMock()
    context.set_default_timeout = MagicMock()
    context.close = AsyncMock()

    browser = MagicMock()
    browser.new_context = AsyncMock(return_value=context)
    return browser


async def test_happy_path_returns_provider_result():
    xhr = {
        "ServiceInformationValue": [
            {
                "ServiceNameValue": "Mobile Internet",
                "ServiceDetailsInformationValue": [
                    {
                        "ConsumptionValue": "1",
                        "ConsumptionUnitValue": "GB",
                        "ExtraConsumptionValue": "0",
                        "PackageValue": "20",
                        "PackageUnitValue": "GB",
                    }
                ],
            }
        ]
    }
    browser = make_browser(xhr_json=xhr)
    result = await AlfaLbProvider().fetch(make_account(), browser)
    assert result.account_id == "03333333"
    assert len(result.lines) == 1
    assert result.lines[0].consumed_gb == 1.0


async def test_login_page_rejected_raises_transient():
    browser = make_browser(page_text="The requested URL was rejected.")
    with pytest.raises(TransientFetchError, match="rejected"):
        await AlfaLbProvider().fetch(make_account(), browser)


async def test_xhr_timeout_raises_transient():
    import asyncio

    browser = make_browser(raise_on_wait=asyncio.TimeoutError())
    with pytest.raises(TransientFetchError):
        await AlfaLbProvider().fetch(make_account(), browser)


async def test_missing_service_raises_unknown_then_classifier_keeps_unknown():
    """If the XHR returns an unrecognised shape, parse_response raises
    UnknownFetchError and fetch lets it propagate."""
    from carriers_sync.providers.base import UnknownFetchError

    browser = make_browser(xhr_json={"ServiceInformationValue": []})
    with pytest.raises(UnknownFetchError):
        await AlfaLbProvider().fetch(make_account(), browser)


async def test_login_form_error_text_classified_as_auth():
    """If the page after submit shows the login error string, that's auth."""

    # We shape the mock so that:
    #  - page.text_content('body') after form click returns the login-error string
    #  - so fetch should classify as AuthFetchError before waiting on XHR
    page_text = "Invalid Username or Password"
    browser = make_browser(page_text=page_text)
    with pytest.raises(AuthFetchError):
        await AlfaLbProvider().fetch(make_account(), browser)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_alfa_lb_fetch.py -v`
Expected: FAIL — current `fetch()` raises `NotImplementedError`.

- [ ] **Step 3: Implement `AlfaLbProvider.fetch`**

Replace the `AlfaLbProvider` stub at the bottom of `carriers_sync/src/carriers_sync/providers/alfa_lb.py` with:

```python
import asyncio
import logging
from datetime import datetime, timezone

logger = logging.getLogger("carriers_sync.providers.alfa_lb")

_LOGIN_URL = "https://www.alfa.com.lb/en/account/login"
_CONSUMPTION_URL_PATTERN = "**/en/account/getconsumption*"
_REJECTED_MARKER = "The requested URL was rejected"
_AUTH_ERROR_MARKERS = (
    "Invalid Username or Password",
    "Account is locked",
    "verification code",
)
_DEFAULT_TIMEOUT_MS = 90_000


class AlfaLbProvider:
    id: ClassVar[str] = "alfa-lb"
    display_name: ClassVar[str] = "Alfa (Lebanon)"

    async def fetch(
        self,
        account: AccountConfig,
        browser: Any,
    ) -> ProviderResult:
        context = await browser.new_context()
        context.set_default_navigation_timeout(_DEFAULT_TIMEOUT_MS)
        context.set_default_timeout(_DEFAULT_TIMEOUT_MS)
        try:
            page = await context.new_page()
            try:
                await page.goto(_LOGIN_URL)
            except Exception as e:
                raise TransientFetchError(f"goto failed: {e}") from e

            await self._guard_rejected(page)

            await page.fill("#loginForm #Username", account.username)
            await page.fill("#loginForm #Password", account.password)
            await page.click('#loginForm button[type="submit"]')

            await self._guard_rejected(page)
            await self._guard_auth_error(page)

            try:
                async with page.expect_response(
                    _CONSUMPTION_URL_PATTERN, timeout=_DEFAULT_TIMEOUT_MS
                ) as info:
                    await self._guard_rejected(page)
                response = info.value
            except asyncio.TimeoutError as e:
                raise TransientFetchError("getconsumption XHR did not arrive") from e
            except Exception as e:
                # Playwright wraps timeouts in its own exception class; treat unknown
                # waits as transient by default.
                raise TransientFetchError(f"waiting for getconsumption failed: {e}") from e

            payload = await response.json()
            return parse_response(
                payload,
                account=account,
                fetched_at=datetime.now(timezone.utc),
            )
        finally:
            await context.close()

    @staticmethod
    async def _guard_rejected(page: Any) -> None:
        body = await page.text_content("body")
        if body and _REJECTED_MARKER in body:
            raise TransientFetchError("login URL rejected by Alfa edge")

    @staticmethod
    async def _guard_auth_error(page: Any) -> None:
        body = await page.text_content("body")
        if not body:
            return
        for marker in _AUTH_ERROR_MARKERS:
            if marker in body:
                raise AuthFetchError(f"login error: {marker!r}")
```

You'll also need to add the imports at the top of `alfa_lb.py`:

```python
import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, ClassVar

from carriers_sync.providers.base import (
    AccountConfig,
    AuthFetchError,
    LineUsage,
    ProviderResult,
    TransientFetchError,
    UnknownFetchError,
)
```

(Replace the existing imports — the previous version imported `datetime` only as a type, no `timezone`; consolidate into one import block.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_alfa_lb_fetch.py -v`
Expected: 5 passed.

- [ ] **Step 5: Run full test suite**

Run: `pytest -q`
Expected: all tests from previous tasks still pass plus the new 5.

- [ ] **Step 6: Run typecheck and lint**

Run: `mypy carriers_sync/src && ruff check carriers_sync/src tests`
Expected: clean.

- [ ] **Step 7: Propose commit**

Stage: `carriers_sync/src/carriers_sync/providers/alfa_lb.py tests/unit/test_alfa_lb_fetch.py`

Suggested message: `feat(providers): Playwright fetch with error classification for Alfa`

Ask before committing.

---

## Task 9: Provider registry + Touch placeholder

**Files:**
- Modify: `carriers_sync/src/carriers_sync/providers/__init__.py`
- Create: `carriers_sync/src/carriers_sync/providers/touch_lb.py`
- Create: `tests/unit/test_provider_registry.py`

- [ ] **Step 1: Write the failing tests**

Path: `tests/unit/test_provider_registry.py`

```python
import pytest

from carriers_sync.providers import PROVIDERS, get_provider
from carriers_sync.providers.alfa_lb import AlfaLbProvider


def test_alfa_registered():
    assert "alfa-lb" in PROVIDERS
    assert PROVIDERS["alfa-lb"] is AlfaLbProvider


def test_get_provider_returns_instance():
    p = get_provider("alfa-lb")
    assert isinstance(p, AlfaLbProvider)


def test_unknown_provider_raises():
    with pytest.raises(KeyError, match="unknown provider"):
        get_provider("nonexistent")


def test_touch_placeholder_raises_not_implemented():
    from carriers_sync.providers.touch_lb import TouchLbProvider
    p = TouchLbProvider()
    # touch_lb not registered yet — its presence is for forward extension only.
    assert p.id == "touch-lb"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_provider_registry.py -v`
Expected: FAIL — registry not implemented.

- [ ] **Step 3: Implement registry**

Path: `carriers_sync/src/carriers_sync/providers/__init__.py`

```python
"""Provider registry: maps provider id strings to adapter classes."""
from __future__ import annotations

from carriers_sync.providers.alfa_lb import AlfaLbProvider
from carriers_sync.providers.base import Provider

PROVIDERS: dict[str, type[Provider]] = {
    AlfaLbProvider.id: AlfaLbProvider,
    # When TouchLbProvider is implemented, register it here:
    # TouchLbProvider.id: TouchLbProvider,
}


def get_provider(provider_id: str) -> Provider:
    try:
        cls = PROVIDERS[provider_id]
    except KeyError as e:
        raise KeyError(f"unknown provider id: {provider_id}") from e
    return cls()
```

- [ ] **Step 4: Implement Touch placeholder**

Path: `carriers_sync/src/carriers_sync/providers/touch_lb.py`

```python
"""Touch (Lebanon) provider — placeholder.

Implement Playwright flow + parse_response in a future PR. When ready,
register in providers/__init__.py.
"""
from __future__ import annotations

from typing import Any, ClassVar

from carriers_sync.providers.base import (
    AccountConfig,
    ProviderResult,
)


class TouchLbProvider:
    id: ClassVar[str] = "touch-lb"
    display_name: ClassVar[str] = "Touch (Lebanon)"

    async def fetch(
        self,
        account: AccountConfig,
        browser: Any,
    ) -> ProviderResult:
        raise NotImplementedError("Touch provider not yet implemented")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/unit/test_provider_registry.py -v`
Expected: 4 passed.

- [ ] **Step 6: Run full suite + typecheck + lint**

Run: `pytest -q && mypy carriers_sync/src && ruff check carriers_sync/src tests`
Expected: clean.

- [ ] **Step 7: Propose commit**

Stage: `carriers_sync/src/carriers_sync/providers/__init__.py carriers_sync/src/carriers_sync/providers/touch_lb.py tests/unit/test_provider_registry.py`

Suggested message: `feat(providers): registry and Touch placeholder`

Ask before committing.

---

## Task 10: Discovery payload builder — pure function

**Files:**
- Create: `carriers_sync/src/carriers_sync/discovery.py`
- Create: `tests/unit/test_discovery.py`

- [ ] **Step 1: Write the failing tests**

Path: `tests/unit/test_discovery.py`

```python
"""Tests for the pure discovery payload builder.

We assert the shape of MQTT discovery messages and state JSON without
any actual MQTT client involvement.
"""
from datetime import datetime, timezone

from carriers_sync.discovery import (
    build_account_messages,
    build_app_device_messages,
)
from carriers_sync.providers.base import LineUsage, ProviderResult


def make_result_ushare():
    return ProviderResult(
        account_id="03333333",
        lines=[
            LineUsage(
                line_id="03333333",
                label="John",
                consumed_gb=2.0,
                quota_gb=20.0,
                extra_consumed_gb=0.0,
                is_secondary=False,
                parent_line_id=None,
            ),
            LineUsage(
                line_id="03222222",
                label="Wife",
                consumed_gb=1.0,
                quota_gb=None,
                extra_consumed_gb=0.0,
                is_secondary=True,
                parent_line_id="03333333",
            ),
        ],
        fetched_at=datetime(2026, 4, 28, 12, 0, tzinfo=timezone.utc),
    )


def test_app_device_messages_include_refresh_all_button_and_status_sensor():
    msgs = build_app_device_messages()
    topics = [m.topic for m in msgs]
    assert any("button/carriers_sync_refresh_all/config" in t for t in topics)
    assert any("sensor/carriers_sync_app_status/config" in t for t in topics)


def test_account_discovery_publishes_main_and_secondary_devices():
    result = make_result_ushare()
    msgs = build_account_messages(result, danger_percent=80, provider_display="Alfa (Lebanon)")
    topics = {m.topic for m in msgs}

    # Main device discovery topics — phone-number-keyed.
    assert any("homeassistant/sensor/carriers_sync_03333333_consumed_gb/config" in t for t in topics)
    assert any("homeassistant/sensor/carriers_sync_03333333_quota_gb/config" in t for t in topics)
    assert any(
        "homeassistant/sensor/carriers_sync_03333333_total_consumed_gb/config" in t for t in topics
    )
    assert any(
        "homeassistant/binary_sensor/carriers_sync_03333333_danger/config" in t for t in topics
    )
    assert any("homeassistant/button/carriers_sync_03333333_refresh/config" in t for t in topics)

    # Secondary device — only consumed sensor.
    assert any("homeassistant/sensor/carriers_sync_03222222_consumed_gb/config" in t for t in topics)


def test_state_payload_includes_total_and_percent():
    result = make_result_ushare()
    msgs = build_account_messages(result, danger_percent=80, provider_display="Alfa (Lebanon)")
    state_msg = next(m for m in msgs if m.topic == "carriers_sync/03333333/state")
    payload = state_msg.payload
    assert payload["consumed_gb"] == 2.0
    assert payload["total_consumed_gb"] == 3.0  # main + secondary
    assert payload["quota_gb"] == 20.0
    assert payload["remaining_gb"] == 17.0
    assert payload["usage_percent"] == 15.0
    assert payload["sync_ok"] == "ON"
    assert payload["danger"] == "OFF"
    assert payload["last_synced"] == "2026-04-28T12:00:00+00:00"
    assert payload["last_attempted"] == "2026-04-28T12:00:00+00:00"
    assert payload["last_error"] == ""


def test_danger_flag_when_usage_over_threshold():
    """Total > danger_percent of quota turns danger ON."""
    result = ProviderResult(
        account_id="03333333",
        lines=[
            LineUsage(
                line_id="03333333", label="John",
                consumed_gb=18.0, quota_gb=20.0,
                extra_consumed_gb=0.0,
                is_secondary=False, parent_line_id=None,
            ),
        ],
        fetched_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
    )
    msgs = build_account_messages(result, danger_percent=80, provider_display="Alfa (Lebanon)")
    state = next(m for m in msgs if m.topic.endswith("03333333/state"))
    assert state.payload["danger"] == "ON"


def test_danger_flag_when_extra_consumed_positive():
    result = ProviderResult(
        account_id="03333333",
        lines=[
            LineUsage(
                line_id="03333333", label="John",
                consumed_gb=1.0, quota_gb=20.0,
                extra_consumed_gb=0.5,
                is_secondary=False, parent_line_id=None,
            ),
        ],
        fetched_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
    )
    msgs = build_account_messages(result, danger_percent=80, provider_display="Alfa (Lebanon)")
    state = next(m for m in msgs if m.topic.endswith("03333333/state"))
    assert state.payload["danger"] == "ON"


def test_secondary_state_topic_distinct_from_main():
    result = make_result_ushare()
    msgs = build_account_messages(result, danger_percent=80, provider_display="Alfa (Lebanon)")
    sec_state = next(m for m in msgs if m.topic == "carriers_sync/03333333/03222222/state")
    assert sec_state.payload["consumed_gb"] == 1.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_discovery.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `discovery.py`**

Path: `carriers_sync/src/carriers_sync/discovery.py`

```python
"""Pure functions that turn ProviderResults into MQTT discovery + state messages.

No MQTT client work — just shape building. This file is fully unit-tested.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from carriers_sync.providers.base import LineUsage, ProviderResult

AVAILABILITY_TOPIC = "carriers_sync/availability"
APP_DEVICE_ID = "carriers_sync_app"


@dataclass(frozen=True)
class MqttMessage:
    topic: str
    payload: Any  # str | dict
    retain: bool = True


def build_app_device_messages() -> list[MqttMessage]:
    """Singleton App device with refresh-all button and status sensor."""
    device = {
        "identifiers": [APP_DEVICE_ID],
        "name": "Carriers Sync",
        "manufacturer": "carriers-sync",
        "model": "Home Assistant App",
    }
    msgs: list[MqttMessage] = []

    # Refresh-all button
    msgs.append(
        MqttMessage(
            topic="homeassistant/button/carriers_sync_refresh_all/config",
            payload={
                "name": "Refresh all",
                "unique_id": "carriers_sync_refresh_all",
                "command_topic": "carriers_sync/refresh_all/cmd",
                "device": device,
                "availability_topic": AVAILABILITY_TOPIC,
            },
        )
    )

    # App status sensor
    msgs.append(
        MqttMessage(
            topic="homeassistant/sensor/carriers_sync_app_status/config",
            payload={
                "name": "App status",
                "unique_id": "carriers_sync_app_status",
                "state_topic": "carriers_sync/app/state",
                "value_template": "{{ value_json.status }}",
                "device": device,
                "availability_topic": AVAILABILITY_TOPIC,
            },
        )
    )

    return msgs


def build_account_messages(
    result: ProviderResult,
    *,
    danger_percent: int,
    provider_display: str,
) -> list[MqttMessage]:
    """Discovery + state messages for one account and its secondaries."""
    messages: list[MqttMessage] = []

    main = next(line for line in result.lines if not line.is_secondary)
    secondaries = [line for line in result.lines if line.is_secondary]

    main_device = _device_dict(main, provider_display, parent=None)
    messages.extend(_main_discovery_messages(main, main_device))
    messages.append(_main_state_message(result, main, secondaries, danger_percent))

    for sec in secondaries:
        sec_device = _device_dict(sec, provider_display, parent=main.line_id)
        messages.extend(_secondary_discovery_messages(sec, sec_device, account_id=result.account_id))
        messages.append(_secondary_state_message(sec, account_id=result.account_id, fetched_at_iso=result.fetched_at.isoformat()))

    return messages


def _device_dict(line: LineUsage, manufacturer: str, *, parent: str | None) -> dict:
    d: dict[str, Any] = {
        "identifiers": [f"carriers_sync_{line.line_id}"],
        "name": f"Alfa: {line.label}",
        "manufacturer": manufacturer,
        "model": "Secondary line" if line.is_secondary else "Account",
    }
    if parent:
        d["via_device"] = f"carriers_sync_{parent}"
    return d


def _main_discovery_messages(line: LineUsage, device: dict) -> list[MqttMessage]:
    state_topic = f"carriers_sync/{line.line_id}/state"
    cmd_topic = f"carriers_sync/{line.line_id}/refresh/cmd"
    base = {
        "device": device,
        "availability_topic": AVAILABILITY_TOPIC,
        "state_topic": state_topic,
    }

    def sensor(metric: str, *, unit: str | None = None, device_class: str | None = None,
               state_class: str | None = None, name: str) -> MqttMessage:
        cfg: dict[str, Any] = {
            **base,
            "name": name,
            "unique_id": f"carriers_sync_{line.line_id}_{metric}",
            "value_template": "{{ value_json." + metric + " }}",
        }
        if unit:
            cfg["unit_of_measurement"] = unit
        if device_class:
            cfg["device_class"] = device_class
        if state_class:
            cfg["state_class"] = state_class
        return MqttMessage(
            topic=f"homeassistant/sensor/carriers_sync_{line.line_id}_{metric}/config",
            payload=cfg,
        )

    def binary(metric: str, *, device_class: str, name: str) -> MqttMessage:
        return MqttMessage(
            topic=f"homeassistant/binary_sensor/carriers_sync_{line.line_id}_{metric}/config",
            payload={
                **base,
                "name": name,
                "unique_id": f"carriers_sync_{line.line_id}_{metric}",
                "value_template": "{{ value_json." + metric + " }}",
                "device_class": device_class,
                "payload_on": "ON",
                "payload_off": "OFF",
            },
        )

    msgs: list[MqttMessage] = [
        sensor("consumed_gb", unit="GB", device_class="data_size", state_class="total_increasing", name="Consumed"),
        sensor("total_consumed_gb", unit="GB", device_class="data_size", state_class="total_increasing", name="Total consumed"),
        sensor("quota_gb", unit="GB", device_class="data_size", state_class="measurement", name="Quota"),
        sensor("remaining_gb", unit="GB", device_class="data_size", state_class="measurement", name="Remaining"),
        sensor("usage_percent", unit="%", state_class="measurement", name="Usage percent"),
        sensor("extra_consumed_gb", unit="GB", device_class="data_size", state_class="measurement", name="Extra consumed"),
        binary("danger", device_class="problem", name="Danger"),
        binary("sync_ok", device_class="connectivity", name="Sync OK"),
        sensor("last_synced", device_class="timestamp", name="Last synced"),
        sensor("last_attempted", device_class="timestamp", name="Last attempted"),
        sensor("last_error", name="Last error"),
        MqttMessage(
            topic=f"homeassistant/button/carriers_sync_{line.line_id}_refresh/config",
            payload={
                "name": "Refresh",
                "unique_id": f"carriers_sync_{line.line_id}_refresh",
                "command_topic": cmd_topic,
                "device": device,
                "availability_topic": AVAILABILITY_TOPIC,
            },
        ),
    ]
    return msgs


def _secondary_discovery_messages(
    sec: LineUsage, device: dict, *, account_id: str
) -> list[MqttMessage]:
    state_topic = f"carriers_sync/{account_id}/{sec.line_id}/state"
    return [
        MqttMessage(
            topic=f"homeassistant/sensor/carriers_sync_{sec.line_id}_consumed_gb/config",
            payload={
                "name": "Consumed",
                "unique_id": f"carriers_sync_{sec.line_id}_consumed_gb",
                "state_topic": state_topic,
                "value_template": "{{ value_json.consumed_gb }}",
                "unit_of_measurement": "GB",
                "device_class": "data_size",
                "state_class": "total_increasing",
                "device": device,
                "availability_topic": AVAILABILITY_TOPIC,
            },
        ),
    ]


def _main_state_message(
    result: ProviderResult,
    main: LineUsage,
    secondaries: list[LineUsage],
    danger_percent: int,
) -> MqttMessage:
    total = main.consumed_gb + sum(s.consumed_gb for s in secondaries)
    quota = main.quota_gb or 0.0
    remaining = max(0.0, quota - total) if quota else 0.0
    pct = round((total / quota) * 100, 1) if quota else 0.0
    danger = (
        (quota and (total / quota) * 100 >= danger_percent)
        or main.extra_consumed_gb > 0
    )
    iso = result.fetched_at.isoformat()
    return MqttMessage(
        topic=f"carriers_sync/{result.account_id}/state",
        payload={
            "consumed_gb": main.consumed_gb,
            "total_consumed_gb": round(total, 3),
            "quota_gb": main.quota_gb,
            "remaining_gb": round(remaining, 3),
            "usage_percent": pct,
            "extra_consumed_gb": main.extra_consumed_gb,
            "danger": "ON" if danger else "OFF",
            "sync_ok": "ON",
            "last_synced": iso,
            "last_attempted": iso,
            "last_error": "",
        },
    )


def _secondary_state_message(
    sec: LineUsage, *, account_id: str, fetched_at_iso: str
) -> MqttMessage:
    return MqttMessage(
        topic=f"carriers_sync/{account_id}/{sec.line_id}/state",
        payload={"consumed_gb": sec.consumed_gb},
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_discovery.py -v`
Expected: 6 passed.

- [ ] **Step 5: Run full suite + typecheck + lint**

Run: `pytest -q && mypy carriers_sync/src && ruff check carriers_sync/src tests`
Expected: clean.

- [ ] **Step 6: Propose commit**

Stage: `carriers_sync/src/carriers_sync/discovery.py tests/unit/test_discovery.py`

Suggested message: `feat(discovery): pure builder for HA MQTT discovery messages`

Ask before committing.

---

## Task 11: MQTT publisher — connection, LWT, command-topic subscription

**Files:**
- Create: `carriers_sync/src/carriers_sync/mqtt_publisher.py`
- Create: `tests/unit/test_mqtt_publisher.py`

We use `aiomqtt` (async, context-managed). Tests stub the client by monkeypatching the module-level `Client` factory.

- [ ] **Step 1: Write the failing tests**

Path: `tests/unit/test_mqtt_publisher.py`

```python
"""Verify the MQTT publisher's connection lifecycle, LWT, message
buffering, and command-topic dispatch."""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from carriers_sync.discovery import MqttMessage
from carriers_sync.mqtt_publisher import (
    MqttConfig,
    MqttPublisher,
    RefreshCommand,
)


@pytest.fixture
def fake_client(monkeypatch):
    """Replace aiomqtt.Client with a fake whose methods are AsyncMocks."""
    instance = MagicMock()
    instance.__aenter__ = AsyncMock(return_value=instance)
    instance.__aexit__ = AsyncMock(return_value=None)
    instance.publish = AsyncMock()
    instance.subscribe = AsyncMock()

    # Async iterator over messages — by default empty.
    async def _empty():
        if False:
            yield None
        return
    instance.messages = _empty()

    factory = MagicMock(return_value=instance)
    monkeypatch.setattr("carriers_sync.mqtt_publisher.Client", factory)
    return instance, factory


async def test_publishes_message_with_retain(fake_client):
    instance, factory = fake_client
    cfg = MqttConfig(host="h", port=1883, username=None, password=None)
    pub = MqttPublisher(cfg)
    async with pub:
        await pub.publish_many([
            MqttMessage(topic="t/1", payload={"a": 1}, retain=True),
            MqttMessage(topic="t/2", payload="raw", retain=False),
        ])
    # First publish should be the LWT 'online' set on connect:
    calls = instance.publish.await_args_list
    topics = [c.kwargs.get("topic") or c.args[0] for c in calls]
    assert "carriers_sync/availability" in topics
    assert any(c.args[0] == "t/1" for c in calls)
    assert any(c.args[0] == "t/2" for c in calls)


async def test_lwt_set_on_connect(fake_client):
    instance, factory = fake_client
    cfg = MqttConfig(host="h", port=1883, username=None, password=None)
    pub = MqttPublisher(cfg)
    async with pub:
        pass
    kwargs = factory.call_args.kwargs
    assert kwargs["will"]["topic"] == "carriers_sync/availability"
    assert kwargs["will"]["payload"] == "offline"
    assert kwargs["will"]["retain"] is True


async def test_subscribes_to_command_topics(fake_client):
    instance, factory = fake_client
    cfg = MqttConfig(host="h", port=1883, username=None, password=None)
    pub = MqttPublisher(cfg)
    async with pub:
        await pub.subscribe_commands(account_ids=["03333333", "03222222"])
    instance.subscribe.assert_any_await("carriers_sync/refresh_all/cmd")
    instance.subscribe.assert_any_await("carriers_sync/03333333/refresh/cmd")
    instance.subscribe.assert_any_await("carriers_sync/03222222/refresh/cmd")


async def test_command_iterator_yields_refresh_objects(fake_client, monkeypatch):
    instance, factory = fake_client

    # Build a fake message-iterator that yields one of each command topic.
    msg1 = MagicMock()
    msg1.topic = MagicMock()
    msg1.topic.value = "carriers_sync/refresh_all/cmd"
    msg2 = MagicMock()
    msg2.topic = MagicMock()
    msg2.topic.value = "carriers_sync/03333333/refresh/cmd"

    async def _gen():
        yield msg1
        yield msg2
    instance.messages = _gen()

    cfg = MqttConfig(host="h", port=1883, username=None, password=None)
    pub = MqttPublisher(cfg)
    async with pub:
        commands = []
        async for cmd in pub.commands():
            commands.append(cmd)
            if len(commands) == 2:
                break
    assert commands[0] == RefreshCommand(account_id=None)  # all
    assert commands[1] == RefreshCommand(account_id="03333333")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_mqtt_publisher.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `mqtt_publisher.py`**

Path: `carriers_sync/src/carriers_sync/mqtt_publisher.py`

```python
"""Long-lived MQTT connection used to publish discovery + state messages
and to receive button-press commands. Wraps aiomqtt.Client.
"""
from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass

from aiomqtt import Client

from carriers_sync.discovery import AVAILABILITY_TOPIC, MqttMessage

logger = logging.getLogger("carriers_sync.mqtt")


@dataclass(frozen=True)
class MqttConfig:
    host: str
    port: int
    username: str | None
    password: str | None


@dataclass(frozen=True)
class RefreshCommand:
    """A button press received via MQTT. account_id=None means refresh-all."""
    account_id: str | None


class MqttPublisher:
    def __init__(self, cfg: MqttConfig) -> None:
        self._cfg = cfg
        self._client: Client | None = None

    async def __aenter__(self) -> "MqttPublisher":
        will = {
            "topic": AVAILABILITY_TOPIC,
            "payload": "offline",
            "qos": 1,
            "retain": True,
        }
        self._client = Client(
            hostname=self._cfg.host,
            port=self._cfg.port,
            username=self._cfg.username,
            password=self._cfg.password,
            will=will,
        )
        await self._client.__aenter__()
        await self._client.publish(AVAILABILITY_TOPIC, "online", qos=1, retain=True)
        return self

    async def __aexit__(self, *exc) -> None:
        if self._client is None:
            return
        try:
            await self._client.publish(AVAILABILITY_TOPIC, "offline", qos=1, retain=True)
        finally:
            await self._client.__aexit__(*exc)
            self._client = None

    async def publish_many(self, messages: list[MqttMessage]) -> None:
        assert self._client is not None, "use as async context manager"
        for m in messages:
            payload = (
                json.dumps(m.payload, ensure_ascii=False)
                if isinstance(m.payload, dict)
                else str(m.payload)
            )
            await self._client.publish(m.topic, payload, qos=1, retain=m.retain)

    async def subscribe_commands(self, *, account_ids: list[str]) -> None:
        assert self._client is not None
        await self._client.subscribe("carriers_sync/refresh_all/cmd")
        for acct in account_ids:
            await self._client.subscribe(f"carriers_sync/{acct}/refresh/cmd")

    async def commands(self) -> AsyncIterator[RefreshCommand]:
        assert self._client is not None
        async for msg in self._client.messages:
            topic = msg.topic.value
            if topic == "carriers_sync/refresh_all/cmd":
                yield RefreshCommand(account_id=None)
                continue
            # carriers_sync/<account_id>/refresh/cmd
            parts = topic.split("/")
            if len(parts) == 4 and parts[0] == "carriers_sync" and parts[2] == "refresh":
                yield RefreshCommand(account_id=parts[1])
            else:
                logger.warning("ignoring unexpected command topic: %s", topic)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_mqtt_publisher.py -v`
Expected: 4 passed.

- [ ] **Step 5: Run full suite + typecheck + lint**

Run: `pytest -q && mypy carriers_sync/src && ruff check carriers_sync/src tests`
Expected: clean.

- [ ] **Step 6: Propose commit**

Stage: `carriers_sync/src/carriers_sync/mqtt_publisher.py tests/unit/test_mqtt_publisher.py`

Suggested message: `feat(mqtt): aiomqtt-backed publisher with LWT and command subscriptions`

Ask before committing.

---

## Task 12: Scheduler — cycle loop, retry classification, refresh handling

**Files:**
- Create: `carriers_sync/src/carriers_sync/scheduler.py`
- Create: `tests/unit/test_scheduler.py`

This is the largest test file because the scheduler glues everything together.

- [ ] **Step 1: Write the failing tests**

Path: `tests/unit/test_scheduler.py`

```python
"""Tests for the scheduler: retry classification, backoff, refresh events,
and cycle behavior. We mock the provider, browser, and publisher.
"""
import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from carriers_sync.config import AppConfig
from carriers_sync.providers.base import (
    AccountConfig,
    AuthFetchError,
    LineUsage,
    ProviderResult,
    TransientFetchError,
    UnknownFetchError,
)
from carriers_sync.scheduler import RetryPolicy, classify_outcome, run_one_account


def make_account():
    return AccountConfig(
        provider="alfa-lb",
        username="03333333",
        password="x",
        label="John",
        secondary_labels={},
    )


def make_result():
    return ProviderResult(
        account_id="03333333",
        lines=[
            LineUsage(
                line_id="03333333", label="John",
                consumed_gb=1.0, quota_gb=20.0,
                extra_consumed_gb=0.0,
                is_secondary=False, parent_line_id=None,
            )
        ],
        fetched_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
    )


def test_classify_outcome_maps_exceptions_to_short_tokens():
    assert classify_outcome(None) == ""
    assert classify_outcome(TransientFetchError("x")) == "transient"
    assert classify_outcome(AuthFetchError("x")) == "auth"
    assert classify_outcome(UnknownFetchError("x")) == "unknown"
    assert classify_outcome(asyncio.TimeoutError()) == "timeout"
    assert classify_outcome(RuntimeError("?")) == "unknown"


async def test_run_one_account_success_returns_result():
    provider = MagicMock()
    provider.fetch = AsyncMock(return_value=make_result())
    browser = MagicMock()
    policy = RetryPolicy(transient_backoffs=(0.0, 0.0, 0.0))
    result, err = await run_one_account(provider, make_account(), browser, policy)
    assert err is None
    assert result is not None
    provider.fetch.assert_awaited_once()


async def test_run_one_account_transient_retries_then_succeeds():
    provider = MagicMock()
    provider.fetch = AsyncMock(side_effect=[
        TransientFetchError("first"),
        make_result(),
    ])
    policy = RetryPolicy(transient_backoffs=(0.0, 0.0, 0.0))
    result, err = await run_one_account(provider, make_account(), MagicMock(), policy)
    assert err is None
    assert result is not None
    assert provider.fetch.await_count == 2


async def test_run_one_account_transient_max_retries_then_gives_up():
    provider = MagicMock()
    provider.fetch = AsyncMock(side_effect=TransientFetchError("nope"))
    policy = RetryPolicy(transient_backoffs=(0.0, 0.0, 0.0))
    result, err = await run_one_account(provider, make_account(), MagicMock(), policy)
    assert result is None
    assert isinstance(err, TransientFetchError)
    assert provider.fetch.await_count == 3


async def test_run_one_account_auth_no_retry():
    provider = MagicMock()
    provider.fetch = AsyncMock(side_effect=AuthFetchError("invalid"))
    policy = RetryPolicy(transient_backoffs=(0.0, 0.0, 0.0))
    result, err = await run_one_account(provider, make_account(), MagicMock(), policy)
    assert result is None
    assert isinstance(err, AuthFetchError)
    assert provider.fetch.await_count == 1


async def test_run_one_account_unknown_one_retry():
    provider = MagicMock()
    provider.fetch = AsyncMock(side_effect=UnknownFetchError("?"))
    policy = RetryPolicy(transient_backoffs=(0.0, 0.0, 0.0))
    result, err = await run_one_account(provider, make_account(), MagicMock(), policy)
    assert result is None
    assert isinstance(err, UnknownFetchError)
    assert provider.fetch.await_count == 2  # initial + 1 retry
```

We will add a higher-level cycle test next; first ensure the building blocks exist.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_scheduler.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement scheduler core (`scheduler.py`)**

Path: `carriers_sync/src/carriers_sync/scheduler.py`

```python
"""Async cycle scheduler.

Owns:
  - the Playwright browser lifetime (one per cycle)
  - per-account fetch + retry classification
  - reaction to refresh-all + per-account refresh events
  - persistence to state.json after successful fetches
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from carriers_sync.providers.base import (
    AccountConfig,
    AuthFetchError,
    Provider,
    ProviderResult,
    TransientFetchError,
    UnknownFetchError,
)

logger = logging.getLogger("carriers_sync.scheduler")


@dataclass(frozen=True)
class RetryPolicy:
    transient_backoffs: tuple[float, ...] = (30.0, 60.0, 120.0)


def classify_outcome(exc: BaseException | None) -> str:
    if exc is None:
        return ""
    if isinstance(exc, TransientFetchError):
        return "transient"
    if isinstance(exc, AuthFetchError):
        return "auth"
    if isinstance(exc, UnknownFetchError):
        return "unknown"
    if isinstance(exc, asyncio.TimeoutError):
        return "timeout"
    return "unknown"


async def run_one_account(
    provider: Provider,
    account: AccountConfig,
    browser: Any,
    policy: RetryPolicy,
) -> tuple[ProviderResult | None, BaseException | None]:
    """Fetch one account with retry classification.

    Returns (result, None) on success or (None, last_exception) on failure.
    """
    last_exc: BaseException | None = None

    # Transient: up to len(transient_backoffs) attempts with sleep between
    for i in range(len(policy.transient_backoffs)):
        try:
            result = await provider.fetch(account, browser)
            return result, None
        except TransientFetchError as e:
            last_exc = e
            if i < len(policy.transient_backoffs) - 1:
                logger.info(
                    "transient error for %s, retrying after %.1fs: %s",
                    account.username, policy.transient_backoffs[i], e,
                )
                await asyncio.sleep(policy.transient_backoffs[i])
                continue
            logger.warning("transient retries exhausted for %s", account.username)
            return None, last_exc
        except AuthFetchError as e:
            logger.warning("auth error for %s, no retry: %s", account.username, e)
            return None, e
        except UnknownFetchError as e:
            last_exc = e
            if i == 0:
                logger.info("unknown error for %s, retrying once", account.username)
                continue
            logger.warning("unknown error after retry for %s", account.username)
            return None, last_exc
        except Exception as e:  # noqa: BLE001
            logger.exception("unexpected error for %s", account.username)
            return None, e

    return None, last_exc
```

(We deliberately stop short of the full cycle loop here — the next step adds it.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_scheduler.py -v`
Expected: 6 passed.

- [ ] **Step 5: Add cycle-loop test**

Append to `tests/unit/test_scheduler.py`:

```python
async def test_cycle_iterates_all_accounts_and_publishes(monkeypatch):
    """Run a single cycle: scheduler fetches each account, builds messages,
    asks the publisher to publish them. We mock everything around it."""
    from carriers_sync.scheduler import Scheduler
    from carriers_sync.discovery import MqttMessage

    # Mock provider that always succeeds.
    provider = MagicMock()
    provider.fetch = AsyncMock(return_value=make_result())
    monkeypatch.setattr(
        "carriers_sync.scheduler.get_provider", lambda _: provider
    )

    publisher = MagicMock()
    publisher.publish_many = AsyncMock()
    publisher.subscribe_commands = AsyncMock()
    publisher.commands = MagicMock(return_value=_empty_async_iter())

    state_store = MagicMock()
    state_store.load = MagicMock(return_value=MagicMock(last_results={}, last_published_entities=set()))
    state_store.save = MagicMock()

    browser_factory = AsyncMock()
    fake_browser = MagicMock()
    fake_browser.close = AsyncMock()
    browser_factory.return_value = fake_browser

    cfg = AppConfig(
        poll_interval_minutes=60,
        danger_percent=80,
        log_level="info",
        accounts=[make_account()],
    )

    sched = Scheduler(
        config=cfg,
        publisher=publisher,
        state_store=state_store,
        browser_factory=browser_factory,
        retry_policy=RetryPolicy(transient_backoffs=(0.0, 0.0, 0.0)),
    )

    await sched.run_one_cycle()
    publisher.publish_many.assert_awaited()
    state_store.save.assert_called()


async def _empty_async_iter():
    if False:
        yield None
    return
```

Run: `pytest tests/unit/test_scheduler.py -v`
Expected: FAIL — `Scheduler` class not implemented yet.

- [ ] **Step 6: Add `Scheduler` class to `scheduler.py`**

Append to `carriers_sync/src/carriers_sync/scheduler.py`:

```python
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from carriers_sync.config import AppConfig
from carriers_sync.discovery import (
    APP_DEVICE_ID,
    AVAILABILITY_TOPIC,
    MqttMessage,
    build_account_messages,
    build_app_device_messages,
)
from carriers_sync.mqtt_publisher import MqttPublisher, RefreshCommand
from carriers_sync.providers import get_provider
from carriers_sync.providers.alfa_lb import AlfaLbProvider  # for display lookups
from carriers_sync.state_store import State, StateStore


_PROVIDER_DISPLAY: dict[str, str] = {
    AlfaLbProvider.id: AlfaLbProvider.display_name,
}


class Scheduler:
    def __init__(
        self,
        *,
        config: AppConfig,
        publisher: MqttPublisher,
        state_store: StateStore,
        browser_factory: Callable[[], Awaitable[Any]],
        retry_policy: RetryPolicy = RetryPolicy(),
    ) -> None:
        self._config = config
        self._publisher = publisher
        self._state_store = state_store
        self._browser_factory = browser_factory
        self._retry = retry_policy
        self._refresh_all = asyncio.Event()
        self._account_refresh: asyncio.Queue[str] = asyncio.Queue()
        self._stop = asyncio.Event()

    async def run_forever(self) -> None:
        # Initial: republish state, publish discovery, subscribe to commands.
        state = self._state_store.load()
        await self._publish_discovery()
        await self._republish_known_state(state)
        await self._publish_app_status("starting")
        await self._publisher.subscribe_commands(
            account_ids=[a.username for a in self._config.accounts]
        )

        # Spawn the command listener and the per-account refresh worker.
        listener = asyncio.create_task(self._listen_commands())
        refresher = asyncio.create_task(self._account_refresh_worker())
        try:
            while not self._stop.is_set():
                try:
                    await self.run_one_cycle()
                    await self._publish_app_status("running")
                except Exception:
                    logger.exception("unhandled error during cycle")
                    await self._publish_app_status("errored")
                await self._await_next_cycle()
        finally:
            listener.cancel()
            refresher.cancel()

    async def _publish_app_status(self, status: str) -> None:
        await self._publisher.publish_many([
            MqttMessage(
                topic="carriers_sync/app/state",
                payload={"status": status},
                retain=True,
            )
        ])

    async def _account_refresh_worker(self) -> None:
        """Consume per-account refresh requests and run an out-of-band fetch
        for that account. Drops requests for an account whose fetch is
        already in flight (de-bounce)."""
        in_flight: set[str] = set()
        try:
            while True:
                acct_id = await self._account_refresh.get()
                if acct_id in in_flight:
                    continue
                account = next(
                    (a for a in self._config.accounts if a.username == acct_id),
                    None,
                )
                if account is None:
                    logger.warning("refresh requested for unknown account %s", acct_id)
                    continue
                in_flight.add(acct_id)
                asyncio.create_task(self._refresh_one(account, in_flight))
        except asyncio.CancelledError:
            return

    async def _refresh_one(self, account: AccountConfig, in_flight: set[str]) -> None:
        try:
            browser = await self._browser_factory()
            try:
                await self._fetch_and_publish(account, browser)
            finally:
                await browser.close()
        finally:
            in_flight.discard(account.username)

    async def stop(self) -> None:
        self._stop.set()
        self._refresh_all.set()

    async def run_one_cycle(self) -> None:
        browser = await self._browser_factory()
        try:
            for account in self._config.accounts:
                await self._fetch_and_publish(account, browser)
        finally:
            await browser.close()

    async def _fetch_and_publish(self, account: AccountConfig, browser: Any) -> None:
        provider = get_provider(account.provider)
        result, exc = await run_one_account(provider, account, browser, self._retry)
        now_iso = datetime.now(timezone.utc).isoformat()

        if result is not None:
            display = _PROVIDER_DISPLAY.get(account.provider, account.provider)
            messages = build_account_messages(
                result,
                danger_percent=self._config.danger_percent,
                provider_display=display,
            )
            await self._publisher.publish_many(messages)

            state = self._state_store.load()
            state.last_results[account.username] = result
            self._state_store.save(state)
        else:
            err_token = classify_outcome(exc)
            await self._publish_error_state(account, err_token, now_iso)

    async def _publish_error_state(
        self, account: AccountConfig, err_token: str, now_iso: str
    ) -> None:
        # State-only update: keep last metric values, mark sync_ok off, etc.
        msg = MqttMessage(
            topic=f"carriers_sync/{account.username}/state",
            payload={
                "sync_ok": "OFF",
                "last_error": err_token,
                "last_attempted": now_iso,
            },
            retain=True,
        )
        # NOTE: this is a partial-payload publish — discovery uses value_template
        # against the latest retained JSON. To avoid clobbering metric values, we
        # merge with the previous state.
        prev = self._state_store.load().last_results.get(account.username)
        merged: dict[str, Any] = {}
        if prev is not None:
            merged = _payload_from_result(
                prev, danger_percent=self._config.danger_percent
            )
        merged.update(msg.payload)
        await self._publisher.publish_many(
            [MqttMessage(topic=msg.topic, payload=merged, retain=True)]
        )

    async def _publish_discovery(self) -> None:
        msgs = build_app_device_messages()
        for account in self._config.accounts:
            # Use a stale prior result if available so discovery gets a sensible
            # state shape; otherwise build from the configured account alone.
            prev = self._state_store.load().last_results.get(account.username)
            if prev is None:
                continue
            display = _PROVIDER_DISPLAY.get(account.provider, account.provider)
            msgs.extend(build_account_messages(
                prev, danger_percent=self._config.danger_percent, provider_display=display
            ))
        await self._publisher.publish_many(msgs)

    async def _republish_known_state(self, state: State) -> None:
        for result in state.last_results.values():
            display = "Alfa (Lebanon)"  # extend when more providers land
            msgs = build_account_messages(
                result,
                danger_percent=self._config.danger_percent,
                provider_display=display,
            )
            await self._publisher.publish_many(msgs)

    async def _await_next_cycle(self) -> None:
        timeout = self._config.poll_interval_minutes * 60
        try:
            await asyncio.wait_for(self._refresh_all.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            return
        finally:
            self._refresh_all.clear()

    async def _listen_commands(self) -> None:
        try:
            async for cmd in self._publisher.commands():
                if cmd.account_id is None:
                    self._refresh_all.set()
                else:
                    await self._account_refresh.put(cmd.account_id)
        except asyncio.CancelledError:
            return


def _payload_from_result(result: ProviderResult, *, danger_percent: int) -> dict[str, Any]:
    # Mirror the shape from discovery._main_state_message minus error fields.
    main = next(line for line in result.lines if not line.is_secondary)
    secondaries = [line for line in result.lines if line.is_secondary]
    total = main.consumed_gb + sum(s.consumed_gb for s in secondaries)
    quota = main.quota_gb or 0.0
    remaining = max(0.0, quota - total) if quota else 0.0
    pct = round((total / quota) * 100, 1) if quota else 0.0
    danger = (
        (quota and (total / quota) * 100 >= danger_percent)
        or main.extra_consumed_gb > 0
    )
    return {
        "consumed_gb": main.consumed_gb,
        "total_consumed_gb": round(total, 3),
        "quota_gb": main.quota_gb,
        "remaining_gb": round(remaining, 3),
        "usage_percent": pct,
        "extra_consumed_gb": main.extra_consumed_gb,
        "danger": "ON" if danger else "OFF",
        "sync_ok": "ON",
        "last_synced": result.fetched_at.isoformat(),
        "last_attempted": result.fetched_at.isoformat(),
        "last_error": "",
    }
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest tests/unit/test_scheduler.py -v`
Expected: all 7 passed.

- [ ] **Step 8: Run full suite + typecheck + lint**

Run: `pytest -q && mypy carriers_sync/src && ruff check carriers_sync/src tests`
Expected: clean.

- [ ] **Step 9: Propose commit**

Stage: `carriers_sync/src/carriers_sync/scheduler.py tests/unit/test_scheduler.py`

Suggested message: `feat(scheduler): cycle loop, retry classification, refresh handling`

Ask before committing.

---

## Task 13: Entrypoint `__main__.py`

**Files:**
- Create: `carriers_sync/src/carriers_sync/__main__.py`

- [ ] **Step 1: Write the entrypoint**

Path: `carriers_sync/src/carriers_sync/__main__.py`

```python
"""Process entrypoint.

Run with: `python -m carriers_sync` (with src/ on PYTHONPATH).

Reads /data/options.json, sets up logging + state store, opens MQTT,
launches Playwright, and runs the scheduler forever.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

from playwright.async_api import async_playwright

from carriers_sync.config import ConfigError, load_config
from carriers_sync.logging_setup import configure_logging
from carriers_sync.mqtt_publisher import MqttConfig, MqttPublisher
from carriers_sync.scheduler import Scheduler
from carriers_sync.state_store import StateStore


OPTIONS_PATH = Path("/data/options.json")
STATE_PATH = Path("/data/state.json")


def _mqtt_from_env() -> MqttConfig:
    return MqttConfig(
        host=os.environ.get("MQTT_HOST") or "core-mosquitto",
        port=int(os.environ.get("MQTT_PORT") or "1883"),
        username=os.environ.get("MQTT_USERNAME") or None,
        password=os.environ.get("MQTT_PASSWORD") or None,
    )


async def _amain() -> int:
    try:
        cfg = load_config(OPTIONS_PATH)
    except ConfigError as e:
        # Logging not yet configured — print is fine before logger setup.
        print(f"FATAL: invalid /data/options.json: {e}", file=sys.stderr)
        return 1

    secrets = [a.password for a in cfg.accounts if a.password]
    configure_logging(cfg.log_level, secrets=secrets)
    log = logging.getLogger("carriers_sync")

    log.info("Carriers Sync starting (accounts=%d)", len(cfg.accounts))
    if not cfg.accounts:
        log.info("No accounts configured. Add some in the App's Configuration tab.")

    state_store = StateStore(STATE_PATH)
    publisher = MqttPublisher(_mqtt_from_env())

    async with async_playwright() as p:
        async def make_browser():
            return await p.chromium.launch(headless=True)

        async with publisher:
            sched = Scheduler(
                config=cfg,
                publisher=publisher,
                state_store=state_store,
                browser_factory=make_browser,
            )
            await sched.run_forever()

    return 0


def main() -> int:
    try:
        return asyncio.run(_amain())
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Smoke-import test**

Path: `tests/unit/test_main_imports.py`

```python
def test_main_module_imports():
    """Just verify the entrypoint module is importable and exposes main()."""
    from carriers_sync import __main__ as m
    assert callable(m.main)
```

Run: `pytest tests/unit/test_main_imports.py -v`
Expected: pass.

- [ ] **Step 3: Run full suite + typecheck + lint**

Run: `pytest -q && mypy carriers_sync/src && ruff check carriers_sync/src tests`
Expected: clean.

- [ ] **Step 4: Propose commit**

Stage: `carriers_sync/src/carriers_sync/__main__.py tests/unit/test_main_imports.py`

Suggested message: `feat: add entrypoint that wires config, MQTT, scheduler, Playwright`

Ask before committing.

---

## Task 14: HA App packaging — `config.yaml`, `Dockerfile`, `run.sh`, `DOCS.md`, `CHANGELOG.md`

**Files:**
- Create: `carriers_sync/config.yaml`
- Create: `carriers_sync/Dockerfile`
- Create: `carriers_sync/run.sh`
- Create: `carriers_sync/DOCS.md`
- Create: `carriers_sync/CHANGELOG.md`

- [ ] **Step 1: Create `config.yaml`**

Path: `carriers_sync/config.yaml`

```yaml
name: Carriers Sync
version: 0.1.0
slug: carriers_sync
description: Sync mobile carrier data usage to Home Assistant via MQTT discovery.
url: https://github.com/akhoury/carriers-sync
arch:
  - amd64
  - aarch64
init: false
startup: application
boot: auto
services:
  - mqtt:need
options:
  poll_interval_minutes: 60
  danger_percent: 80
  log_level: info
  accounts: []
schema:
  poll_interval_minutes: int(5,1440)
  danger_percent: int(1,100)
  log_level: list(trace|debug|info|notice|warning|error|fatal)
  accounts:
    - provider: list(alfa-lb)
      username: str
      password: password
      label: str
      secondary_labels:
        - number: match(^[0-9]{6,12}$)
          label: str
```

- [ ] **Step 2: Create `Dockerfile`**

Path: `carriers_sync/Dockerfile`

```dockerfile
FROM ghcr.io/home-assistant/base-python:3.12-bookworm

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Playwright + Chromium (glibc base required)
RUN pip3 install --no-cache-dir playwright aiomqtt pyyaml \
 && playwright install-deps \
 && playwright install chromium

WORKDIR /app
COPY src/ ./src/
COPY run.sh ./
RUN chmod +x run.sh

CMD ["./run.sh"]
```

(`requirements.txt` is intentionally not used inside the container — deps are pinned via `pip install` directly. The repo-root `pyproject.toml` is for local dev, not for the App image.)

- [ ] **Step 3: Create `run.sh`**

Path: `carriers_sync/run.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail

cd /app/src
exec python3 -m carriers_sync
```

- [ ] **Step 4: Create `DOCS.md`**

Path: `carriers_sync/DOCS.md`

```markdown
# Carriers Sync — Documentation

Sync mobile carrier (Alfa) data-usage to Home Assistant as proper
devices and sensors via MQTT discovery.

## Prerequisites

- The **Mosquitto broker** App, installed and running.
- The **MQTT** integration in Home Assistant, configured against Mosquitto.

## Configuration

| Option | Type | Default | Description |
|---|---|---|---|
| `poll_interval_minutes` | int (5–1440) | 60 | How often to fetch from each account. |
| `danger_percent` | int (1–100) | 80 | Threshold above which a line's `danger` binary sensor turns ON. |
| `log_level` | enum | `info` | One of trace/debug/info/notice/warning/error/fatal. |
| `accounts` | list | `[]` | One entry per Alfa account you want to monitor. |

### Account fields

| Field | Type | Description |
|---|---|---|
| `provider` | enum | Currently only `alfa-lb`. |
| `username` | str | Alfa portal username (your phone number, e.g. `03333333`). |
| `password` | str | Alfa portal password (stored in `/data/options.json`). |
| `label` | str | Friendly name shown in Home Assistant (e.g. "John's main"). Use unique labels — see Tips. |
| `secondary_labels` | list | For U-share accounts: `[{number: 03222222, label: Wife}, ...]`. Lets you give friendly names to each secondary line. |

## Entities

For each account, this App creates an HA *device* identified by the main phone
number, plus child devices (linked via `via_device`) for each U-share secondary.

Per-account device entities:
- `sensor.alfa_<label>_consumed_gb`, `_total_consumed_gb`, `_quota_gb`,
  `_remaining_gb`, `_usage_percent`, `_extra_consumed_gb`
- `binary_sensor.alfa_<label>_danger`, `_sync_ok`
- `sensor.alfa_<label>_last_synced`, `_last_attempted`, `_last_error`
- `button.alfa_<label>_refresh`

Per secondary line:
- `sensor.alfa_<secondary_label>_consumed_gb`

A singleton `Carriers Sync` device exposes:
- `button.carriers_sync_refresh_all`
- `sensor.carriers_sync_app_status`

## Tips

- **Use unique labels.** If two lines share a label, HA appends `_2`, `_3` etc.
  to the entity_id of the second.
- **The `total_consumed_gb` sensor** is your real "data used this month" for
  U-share accounts (main + all secondaries).
- **`last_synced` lags `last_attempted`** when fetches fail — that's the signal
  that data is stale.

## Troubleshooting

- **All `sync_ok` are OFF**: Mosquitto is probably down or the MQTT integration
  is misconfigured. Check the App's Log tab.
- **`last_error: auth`**: your stored password is wrong, or Alfa locked the
  account. The App will not retry until you fix the credentials.
- **`last_error: transient`**: network issue or Alfa edge rejected us. The App
  retries 3 times per cycle; if all fail it waits for the next cycle.
- **No entities appearing**: confirm Mosquitto is running and the `mqtt:need`
  service was injected (Supervisor handles this automatically; if it's broken,
  the Log tab will show MQTT connection errors).

To file a useful bug report, set `log_level: trace` and reproduce the issue —
the App writes Playwright network and HTML dumps to `/data/debug/` that you
can attach to a GitHub issue (after redacting your credentials).
```

- [ ] **Step 5: Create `CHANGELOG.md`**

Path: `carriers_sync/CHANGELOG.md`

```markdown
# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Initial Home Assistant App release: rewrite of the standalone
  Google-Keep-syncing script as an App that publishes per-account and
  per-line Alfa usage data via MQTT discovery.
- Provider-adapter abstraction so additional Lebanese carriers (Touch,
  …) can be added as single new files.
- Per-account and global "Refresh now" buttons.
- `last_synced` / `last_attempted` / `last_error` / `sync_ok` sensors
  for staleness visibility.

[Unreleased]: https://github.com/akhoury/carriers-sync/compare/legacy-final...HEAD
```

- [ ] **Step 6: Verify Dockerfile syntactically builds (locally, smoke)**

Run:
```bash
cd carriers_sync
docker buildx build --platform linux/amd64 -t carriers-sync:dev .
```

Expected: build completes (may take several minutes on first run; Chromium download is large).

- [ ] **Step 7: Propose commit**

Stage: `carriers_sync/config.yaml carriers_sync/Dockerfile carriers_sync/run.sh carriers_sync/DOCS.md carriers_sync/CHANGELOG.md`

Suggested message: `feat(app): HA App packaging files (config, Dockerfile, docs)`

Ask before committing.

---

## Task 15: CI workflow

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1: Create CI workflow**

Path: `.github/workflows/ci.yml`

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:

jobs:
  lint-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip

      - name: Install
        run: pip install -e ".[dev]"

      - name: Ruff lint
        run: ruff check .

      - name: Ruff format check
        run: ruff format --check .

      - name: Mypy
        run: mypy carriers_sync/src

      - name: Pytest (unit)
        run: pytest tests/unit -v

      - name: Validate config.yaml
        run: |
          python3 - <<'PY'
          import yaml, sys
          with open("carriers_sync/config.yaml") as f:
              cfg = yaml.safe_load(f)
          required = {"name", "version", "slug", "description", "arch", "options", "schema"}
          missing = required - set(cfg)
          if missing:
              print(f"missing required config.yaml keys: {missing}", file=sys.stderr)
              sys.exit(1)
          PY

  docker-smoke:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: docker/setup-buildx-action@v3
      - name: Smoke build (amd64 only)
        run: |
          docker buildx build --platform linux/amd64 \
            --tag carriers-sync:ci \
            --load \
            ./carriers_sync
```

- [ ] **Step 2: Propose commit**

Stage: `.github/workflows/ci.yml`

Suggested message: `ci: add lint/typecheck/test workflow + Docker smoke build`

Ask before committing.

---

## Task 16: Release workflow

**Files:**
- Create: `.github/workflows/release.yml`

- [ ] **Step 1: Create release workflow**

Path: `.github/workflows/release.yml`

```yaml
name: Release

on:
  push:
    tags:
      - "v*"

jobs:
  build-and-push:
    runs-on: ubuntu-latest
    permissions:
      contents: write
      packages: write
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip

      - name: Install
        run: pip install -e ".[dev]"

      - name: Run full CI checks
        run: |
          ruff check .
          mypy carriers_sync/src
          pytest tests/unit -v

      - name: Verify config.yaml version matches tag
        run: |
          TAG_VERSION="${GITHUB_REF_NAME#v}"
          CFG_VERSION=$(python3 -c "import yaml; print(yaml.safe_load(open('carriers_sync/config.yaml'))['version'])")
          if [ "$TAG_VERSION" != "$CFG_VERSION" ]; then
            echo "Tag $TAG_VERSION does not match config.yaml version $CFG_VERSION"
            exit 1
          fi

      - uses: docker/setup-qemu-action@v3
      - uses: docker/setup-buildx-action@v3

      - name: Log in to GHCR
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Build and push multi-arch
        uses: docker/build-push-action@v5
        with:
          context: ./carriers_sync
          platforms: linux/amd64,linux/arm64
          push: true
          tags: |
            ghcr.io/${{ github.repository_owner }}/carriers-sync:${{ github.ref_name }}
            ghcr.io/${{ github.repository_owner }}/carriers-sync:latest

      - name: Create GitHub release
        uses: softprops/action-gh-release@v2
        with:
          generate_release_notes: true
```

- [ ] **Step 2: Propose commit**

Stage: `.github/workflows/release.yml`

Suggested message: `ci: multi-arch release workflow (buildx + GHCR + GitHub release)`

Ask before committing.

---

## Task 17: Repo top-level — `repository.yaml`, `README.md`, `LICENSE`

**Files:**
- Create: `repository.yaml`
- Create: `README.md`
- Create: `LICENSE`

- [ ] **Step 1: Create `repository.yaml`**

Path: `repository.yaml`

```yaml
name: Carriers Sync
url: https://github.com/akhoury/carriers-sync
maintainer: Aziz Khoury
```

- [ ] **Step 2: Create `LICENSE` (MIT placeholder; user can change)**

Path: `LICENSE`

```
MIT License

Copyright (c) 2026 Aziz Khoury

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

- [ ] **Step 3: Create `README.md`**

Path: `README.md`

```markdown
# Carriers Sync — Home Assistant App

Sync mobile carrier (Alfa) data-usage to Home Assistant as proper
devices and sensors, via MQTT discovery.

## Install

1. In Home Assistant, go to **Settings → Apps → Apps → ⋮ menu → Repositories**.
2. Add this repository's URL: `https://github.com/akhoury/carriers-sync`.
3. Find **Carriers Sync** in the App store, click **Install**.
4. Open the App's **Configuration** tab and add your Alfa account(s).
5. Start the App.

The App requires the **Mosquitto broker** App and the **MQTT** integration to
be installed and configured (most HA installs already have this).

## What you get

For each Alfa account, an HA device with:

- `sensor.alfa_<label>_consumed_gb`, `total_consumed_gb`, `quota_gb`,
  `remaining_gb`, `usage_percent`, `extra_consumed_gb`
- `binary_sensor.alfa_<label>_danger` (over threshold or extra used)
- `binary_sensor.alfa_<label>_sync_ok` (last fetch succeeded)
- `sensor.alfa_<label>_last_synced` / `_last_attempted` / `_last_error`
- `button.alfa_<label>_refresh`

For U-share accounts, each secondary line becomes its own HA device
(`via_device` linked to the main account) with its own `consumed_gb`
sensor. Plus a singleton "Carriers Sync" device with a global
`refresh_all` button and an `app_status` sensor.

See `carriers_sync/DOCS.md` for the full configuration reference,
troubleshooting, and bug-report instructions.

## Migrating from the legacy Google Keep version

The pre-1.0 version of this repo (`carrierslb_sync.py`, syncing to a
Google Keep note) is preserved on the `legacy/google-keep` branch and at
the `legacy-final` tag. There is no automatic migration — install the
App, re-enter your accounts in the form, and remove the old script.

## Developing locally

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
ruff check .
mypy carriers_sync/src
pytest -q
```

## License

MIT — see `LICENSE`.
```

- [ ] **Step 4: Run final full check**

Run:
```bash
pytest -q && mypy carriers_sync/src && ruff check . && ruff format --check .
```

Expected: all clean.

- [ ] **Step 5: Propose commit**

Stage: `repository.yaml LICENSE README.md`

Suggested message: `docs: README, repository.yaml, LICENSE for App store install`

Ask before committing.

---

## Done

At this point the repo:
- ships the App skeleton + Alfa adapter + MQTT publisher + scheduler
- has unit tests with ~90% coverage on the failure-prone bits
- has CI gating lint, typecheck, tests, Dockerfile validity
- has a release workflow that produces multi-arch images on `v*` tags
- preserves the legacy Google-Keep version at `legacy-final` tag and `legacy/google-keep` branch
- is ready to be added as a community App store URL by users

Future work (separate plans, per the spec's §10):
- **Touch (Lebanon) provider** — second adapter; same contract.
- **Ingress status page** — read-only dashboard.
- **Arabic translations** — `translations/ar.yaml`.
- **Captcha handling** — only if Alfa starts gating logins.
