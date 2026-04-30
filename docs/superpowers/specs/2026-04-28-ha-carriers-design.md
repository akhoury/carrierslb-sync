# Carriers Sync — Home Assistant App Design

**Date:** 2026-04-28
**Status:** Draft
**Audience:** Public community release on a Home Assistant App store repo

## 1. Goal

Convert the current standalone `carriers-sync` Python script (which scrapes mobile carrier (Alfa) usage data via Playwright and writes a formatted note to Google Keep) into a **Home Assistant App** (the artifact formerly known as an "add-on", renamed in HA 2026.2).

The App publishes per-account and per-line usage data as MQTT-discovery sensors so HA auto-creates devices and entities. It is structured around a **provider adapter** abstraction so a second Lebanese carrier (Touch) can be added later as a single new file with no scheduler / publisher changes.

### Supported HA versions

The App will install and run on any HA Supervisor from roughly **2024 onwards** — the `config.yaml` schema features we use (`int`, `list`, `match`, `password`, `services: [mqtt:need]`) have been stable for years, multi-arch manifest pulls are a Docker-layer feature handled by every modern Docker daemon, and we don't depend on `BUILD_FROM` (we hardcode the `FROM` line).

The 2026.04 build-side changes (no `build.yaml`, plain `docker buildx`, retirement of `home-assistant/builder`) affect **how we build and release the image on our CI**, not how users' Supervisors run it. We don't need a backwards-compat build pipeline.

Recommended minimum: HA Supervisor **2024.1** or newer. Tested-against minimum: whatever the current `latest` and the previous minor version are at release time.

## 2. Decisions made during brainstorming

| Decision | Choice | Why |
|---|---|---|
| Distribution target | Public community App store repo | User goal is for any HA user in Lebanon to install it |
| HA surface | App publishing via MQTT discovery (not a companion integration, not REST push) | Idiomatic for container-based HA apps; single-piece install; clean device + sensor model |
| Configuration UX | Standard App options form (HA-auto-rendered from `config.yaml` schema) | Fastest to ship; sufficient for a v1 utility app; ingress UI is a v1.x option |
| MQTT broker | Required prereq (Mosquitto App + MQTT integration) | Most HA users already have it; declared via `services: [mqtt:need]` so Supervisor injects connection details |
| Polling cadence | Single global `poll_interval_minutes` user option (5–1440, default 60) | Simpler than per-account; all accounts hit same site, no benefit to staggering |
| Manual refresh | Per-account "Refresh" buttons + global "Refresh all" button via MQTT discovery + command topic | Standard HA UX, ~30 lines of MQTT plumbing |
| Failure UX | Metric sensors keep last-good values on failure; staleness surfaced via `last_synced` / `last_attempted` / `last_error` / `sync_ok` sensors | Stale data > no data for usage tracking |
| Retry policy | Lives in scheduler (not in adapter contract) | One source of truth; adapters only classify errors |
| Secondary U-share lines | Their own HA devices, linked `via_device` to the parent account | Lets users put each line in different HA areas |
| Entity uniqueness | Keyed on phone number; relabeling preserves entity ID | Friendly_name updates, entity_id stays |
| Credentials storage | `/data/options.json` plaintext (HA convention) | Same as Mosquitto, MariaDB, etc.; HA host is the security boundary |
| State persistence | `/data/state.json` for last `ProviderResult` per account | Survives restarts; lets us republish on startup so sensors don't go blank |
| Web UI inside App | Out of scope for v1 | Standard options form is sufficient |
| Translations | English only in v1 | Arabic is a v1.x candidate |

## 3. Architecture

```
┌──────────────────────────── Home Assistant Host ────────────────────────────┐
│                                                                             │
│  ┌────────────────────────┐                  ┌───────────────────────────┐  │
│  │  carriers-sync App  │     publishes    │    Mosquitto broker App   │  │
│  │  (this repo, container)│ ───── MQTT ────▶ │     (existing prereq)     │  │
│  │                        │                  └───────────┬───────────────┘  │
│  │  ┌──────────────────┐  │                              │ subscribes       │
│  │  │ scheduler loop   │  │                              ▼                  │
│  │  │ (asyncio)        │  │                  ┌──────────────────────────┐   │
│  │  └────────┬─────────┘  │                  │   Home Assistant Core    │   │
│  │           │            │                  │  (MQTT integration)      │   │
│  │  ┌────────▼─────────┐  │                  │  → auto-creates devices  │   │
│  │  │ Provider Adapter │  │                  │    + sensors via         │   │
│  │  │ Registry         │  │                  │    discovery messages    │   │
│  │  │  ├ alfa-lb       │  │                  └──────────────────────────┘   │
│  │  │  └ touch-lb (v2) │  │                                                 │
│  │  └────────┬─────────┘  │                                                 │
│  │           │            │                                                 │
│  │  ┌────────▼─────────┐  │                                                 │
│  │  │ Playwright +     │  │                                                 │
│  │  │ Chromium         │  │                                                 │
│  │  └──────────────────┘  │                                                 │
│  │                        │                                                 │
│  │  /data/                │                                                 │
│  │   ├ options.json (HA-  │                                                 │
│  │   │  managed config)   │                                                 │
│  │   └ state.json (last   │                                                 │
│  │      scrape per acct)  │                                                 │
│  └────────────────────────┘                                                 │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Components

1. **App container** — single Docker image. Base: `ghcr.io/home-assistant/base-python:3.12-bookworm` (Debian / glibc — required because Microsoft's prebuilt Playwright Chromium binaries are glibc-only and break on Alpine/musl). As of Supervisor 2026.03.1+ the HA base images are published as **multi-arch manifests**, so a single `FROM` line covers `amd64` and `aarch64` automatically with no per-arch build logic. Replaces the current `ubuntu:22.04`. Drops `cron` + `supervisord` apt packages: HA Supervisor (capital-S) is the process supervisor and restarts the container on crash.

2. **Scheduler loop** (`scheduler.py`) — async Python entrypoint. Owns the Playwright browser lifetime (one browser per cycle, fresh context per account). Reads `/data/options.json`, iterates accounts, dispatches each to the right provider adapter, gathers `ProviderResult`s, hands them to the MQTT publisher. Implements the retry policy (see §6).

3. **Provider Adapter Registry** (`providers/__init__.py`) — `dict[str, type[Provider]]` mapping provider IDs to classes. Scheduler is provider-agnostic; it just looks up by the account's `provider` field.

4. **Provider adapters** (`providers/alfa_lb.py`, future `providers/touch_lb.py`) — each implements the `Provider` protocol (see §4). Encapsulates one carrier's Playwright flow + JSON parsing + error classification.

5. **MQTT publisher** (`mqtt_publisher.py`) — converts a `ProviderResult` into HA discovery messages + state messages, with retained=true. Provider-agnostic. Holds the long-lived MQTT connection. Subscribes to command topics for the "Refresh" buttons.

6. **State store** (`state_store.py`) — atomic read/write of `/data/state.json`. Holds last successful `ProviderResult` per account, last error, and the set of currently-published discovery entities (for cleanup on account removal).

7. **Config parser** (`config.py`) — reads `/data/options.json`, validates, returns typed dataclasses (`AppConfig`, list of `AccountConfig`).

### What goes away from the current code

- `gkeepapi` and the entire Google Keep note formatting block
- `configparser` + `config.cfg` — replaced by `/data/options.json`
- The blocking `while True / time.sleep` — replaced by async scheduler
- `supervisord.conf`, `run.sh` (in its current form) — replaced by HA's process management

## 4. Provider adapter contract

### File layout

```
src/carriers_sync/
├── __main__.py
├── scheduler.py
├── mqtt_publisher.py
├── state_store.py
├── config.py
├── logging_setup.py
└── providers/
    ├── __init__.py        # registry
    ├── base.py            # Provider protocol + result dataclasses + exceptions
    ├── alfa_lb.py         # Alfa Lebanon adapter (v1)
    └── touch_lb.py        # placeholder, raises NotImplementedError
```

### Contract (`providers/base.py`)

```python
@dataclass(frozen=True)
class AccountConfig:
    provider: str            # "alfa-lb" | "touch-lb" | ...
    username: str
    password: str
    label: str               # user-supplied, e.g. "John's main"
    secondary_labels: dict[str, str]   # phone_number -> label
                                       # NOTE: on disk in /data/options.json this is a
                                       # list of {number, label} objects (HA's schema
                                       # doesn't support free-key maps). config.py
                                       # converts the list to a dict for runtime use.

@dataclass(frozen=True)
class LineUsage:
    """One billable line (main number OR a U-share secondary)."""
    line_id: str             # e.g. "03333333" — stable identity for HA device
    label: str               # user-supplied if known, else line_id
    consumed_gb: float
    quota_gb: float | None   # None for secondaries that share parent's quota
    extra_consumed_gb: float
    is_secondary: bool
    parent_line_id: str | None   # for via_device linking

@dataclass(frozen=True)
class ProviderResult:
    account_id: str          # the username/main number
    lines: list[LineUsage]   # main line + any secondaries
    fetched_at: datetime

class TransientFetchError(Exception):
    """Network timeout, URL rejected, Chromium crash. Worth retrying."""

class AuthFetchError(Exception):
    """Invalid credentials, account locked, captcha. NOT worth retrying this cycle."""

class UnknownFetchError(Exception):
    """Unexpected page structure / JSON shape. One retry, then give up."""

class Provider(Protocol):
    id: ClassVar[str]                   # "alfa-lb"
    display_name: ClassVar[str]         # "Alfa (Lebanon)" — used for HA device manufacturer

    async def fetch(
        self,
        account: AccountConfig,
        browser: playwright.Browser,    # shared across accounts in one cycle
    ) -> ProviderResult: ...
```

### Why this shape

- **Provider-agnostic scheduler & publisher** — they only see `ProviderResult` / `LineUsage`.
- **Adding Touch = one file.** Implement `TouchLbProvider`, register it. No other changes.
- **`LineUsage` is the universal shape** — main lines and U-share secondaries map to the same fields. Forces a healthy minimum-common-denominator across providers.
- **Error classification at the adapter** — only the adapter knows whether "URL was rejected" is transient or permanent for its site. Retry policy stays in scheduler.

### Explicit non-goals for this contract

- No streaming/incremental results (`fetch()` returns one complete result).
- No retry policy in the protocol.
- No provider-specific config fields beyond `username`/`password`/`label`/`secondary_labels`. If Touch needs an extra field (e.g. PIN) we'll add an optional `provider_options: dict[str, str]` escape hatch then.

## 5. Entity model & MQTT discovery

### Device tree

```
Carriers Sync (singleton App device)
├── button.carriers_sync_refresh_all
└── sensor.carriers_sync_app_status      # "starting" | "running" | "errored"

Alfa: John (account device, identified by main number 03333333)
├── sensor.alfa_john_consumed_gb            # main line's own usage
├── sensor.alfa_john_total_consumed_gb      # main + all secondaries
├── sensor.alfa_john_quota_gb               # package quota
├── sensor.alfa_john_remaining_gb           # quota − total
├── sensor.alfa_john_usage_percent          # total / quota × 100
├── sensor.alfa_john_extra_consumed_gb      # overage
├── binary_sensor.alfa_john_danger          # any line > danger_percent OR extra > 0
├── binary_sensor.alfa_john_sync_ok         # last fetch succeeded
├── sensor.alfa_john_last_synced            # datetime of last successful fetch
├── sensor.alfa_john_last_attempted         # datetime of last attempt
├── sensor.alfa_john_last_error             # short token, "" on success
└── button.alfa_john_refresh

  Alfa: Wife (secondary device, via_device → John, identified by 03222222)
  └── sensor.alfa_wife_consumed_gb

  Alfa: Alarm eSIM (secondary device, via_device → John, identified by 03111111)
  └── sensor.alfa_alarm_esim_consumed_gb
```

### Identity & uniqueness

- `unique_id` for every entity is built from the **phone number** (`line_id`), never the label. Relabeling updates `friendly_name`, keeps the entity.
- Device identifiers: `[("carriers_sync", line_id)]`.
- Entity object_id is derived from the slugified label at first creation; HA preserves it on rename (standard HA behavior).
- **Label collisions:** if two accounts/lines share the same label, HA's default behavior appends a numeric suffix to the second entity_id (e.g. `sensor.alfa_john_consumed_gb`, `sensor.alfa_john_consumed_gb_2`). The `unique_id`s are still distinct (line_id-based), so functionality is unaffected; users will just see suffixed entity_ids. README should recommend unique labels.
- **`account_id` assumption:** in `alfa-lb`, `account_id` equals the username (phone number). For other providers that may use non-numeric usernames, the publisher slugifies `account_id` for use in MQTT topics. The `line_id` (always a phone number) is the durable identity for entities.

### Sensor metadata

| Entity | `device_class` | `state_class` | `unit_of_measurement` |
|---|---|---|---|
| `*_consumed_gb`, `*_total_consumed_gb` | `data_size` | `total_increasing` | `GB` |
| `*_quota_gb`, `*_remaining_gb`, `*_extra_consumed_gb` | `data_size` | `measurement` | `GB` |
| `*_usage_percent` | — | `measurement` | `%` |
| `*_last_synced`, `*_last_attempted` | `timestamp` | — | — |
| `*_danger` (binary) | `problem` | — | — |
| `*_sync_ok` (binary) | `connectivity` | — | — |

`total_increasing` is correct for monthly counters that reset — HA handles the reset gracefully.

### MQTT topic structure

```
# Availability (single LWT for the whole App)
carriers_sync/availability                       → "online" | "offline"

# State topics — one consolidated JSON per device
carriers_sync/<account_id>/state                 → JSON with all account-level sensor values
carriers_sync/<account_id>/<line_id>/state       → JSON for secondary line

# Command topics (button presses)
carriers_sync/<account_id>/refresh/cmd
carriers_sync/refresh_all/cmd

# Discovery — standard HA path, retained=true
homeassistant/<component>/carriers_sync_<line_id>_<metric>/config
```

One consolidated state JSON per device (rather than one topic per sensor) with discovery `value_template`s. ~10× less MQTT chatter.

### Lifecycle

- **Startup:** connect MQTT, set LWT to `offline` on availability, publish `online`. Read `/data/state.json` and republish last-known sensor values so HA repopulates without waiting for the first scrape. Publish all discovery messages. Start scheduler loop.
- **Discovery republish:** on startup and on detected config changes (account added/removed/renamed). Not every cycle.
- **Account removal:** on next cycle after the user deletes an account from the form, the scheduler diffs configured accounts against the persisted "last published" set in `state.json` and publishes empty payloads to the relevant `homeassistant/.../config` topics (retained=true), causing HA to remove those entities. Then drops them from `state.json`.
- **Shutdown:** publish `offline` to availability before exit (LWT covers crash case).

## 6. Scheduling, refresh & retry

### Cycle loop

```
on startup:
  republish last-known state from /data/state.json
  publish all discovery messages
  set app_status = "starting"

loop:
  for each account in config:
    fetch with retry (see below)
    update last_attempted, last_error, sync_ok
    on success: update metric sensors + last_synced; persist to state.json
    on failure: leave metric sensors at last value
  set app_status = "running"
  log per-cycle summary
  await poll_interval OR refresh_all_event OR per-account refresh_event
```

### Retry classification

| Exception | Behavior |
|---|---|
| `TransientFetchError` | Backoff 30s → 60s → 120s, max 3 attempts in this cycle |
| `AuthFetchError` | No retry. Surface `last_error: "auth"`. Wait for next cycle. |
| `UnknownFetchError` | One retry only, then give up. `last_error: "unknown"`. Detailed traceback in logs. |

### Manual refresh (MQTT command topics)

- **Per-account refresh** — `button.alfa_<label>_refresh` publishes to `carriers_sync/<account_id>/refresh/cmd`. Scheduler runs **only that account's fetch** out-of-band (does not start a full cycle, does not reset the next-cycle clock). De-bounced: if a fetch for the same account is already running or queued, the press is dropped (no thundering herd).
- **Global refresh-all** — `button.carriers_sync_refresh_all` publishes to `carriers_sync/refresh_all/cmd`. Cancels the current `await poll_interval` and **starts a full cycle now**. The next cycle's clock resets from this trigger.

The cycle loop's `await` waits on three signals (whichever fires first): the poll-interval timeout, the refresh-all event, or any per-account refresh event. Per-account events do not start a cycle — they trigger an out-of-band fetch alongside the running loop and the loop continues its wait.

## 7. Configuration

### Full `config.yaml`

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

### Renames & removals from current code

- `repeat_minutes` → `poll_interval_minutes`
- `danger_percent` stays the name; values change from float `0.8` to int percent `80`
- `timeout` (Playwright) dropped from user-visible config; hardcoded to 90s
- `keep_username`, `keep_token`, `notes_id` — gone (Google Keep removed)
- `alfa_accounts` (top-level JSON blob) → structured `accounts` list
- `alfa_labels` (flat dict) → per-account `label` + `secondary_labels`

### Persistence

| File | Owner | Contents |
|---|---|---|
| `/data/options.json` | Supervisor (auto-written from form) | Validated user options |
| `/data/state.json` | App | Last successful `ProviderResult` per account, last error, last published discovery set |

`/data/` is automatically mounted; no `map:` directive needed.

### Security

- Passwords live in `/data/options.json` plaintext (HA convention; the host is the security boundary).
- Logger has a credential redactor (`logging.Filter` at root) that strips configured passwords from log lines.
- MQTT payloads contain only consumption numbers and labels — never credentials.
- No telemetry / phone-home.

## 8. Error handling, logging & observability

### What the user sees vs what the logs see

| Surface | Detail level |
|---|---|
| Sensor `last_error` | One short token: `""`, `"transient"`, `"auth"`, `"unknown"`, `"timeout"` |
| Sensor `sync_ok` | `on` / `off` |
| Sensor `last_synced` | Timestamp of last *successful* fetch |
| Sensor `last_attempted` | Timestamp of last attempt (any outcome) |
| App log (HA's "Log" tab) | Full traceback, redacted credentials, structured prefixes |

### Logging

- Stdlib `logging`, configured once from the `log_level` option.
- Format: `%(asctime)s [%(levelname)s] %(name)s: %(message)s`.
- Logger names: `carriers_sync.scheduler`, `carriers_sync.mqtt`, `carriers_sync.providers.alfa_lb`, etc.
- Per-cycle summary at INFO: `Cycle complete in 47.2s: 3 ok, 1 auth, 0 transient, 0 unknown`.
- `trace` level dumps full Playwright network traffic + page HTML on failure to `/data/debug/<account_id>-<timestamp>.html` for bug reports. Off by default.

### MQTT failure handling

- **Broker down at startup:** retry every 5s for 60s, then exit non-zero. Supervisor restarts.
- **Mid-cycle disconnect:** buffer up to ~50 messages in memory. On reconnect, flush with retained=true.
- **LWT:** publishes `offline` to `carriers_sync/availability` if our connection dies.

### Crash / restart resilience

- `/data/state.json` is the source of truth on restart. Atomic writes (write to `.tmp`, `os.replace()`).
- On startup: connect MQTT → read `state.json` → republish state → publish discovery → start scheduler.
- Supervisor's auto-restart handles unrecoverable errors. App exits non-zero rather than self-recovers.

### Playwright resilience

- One browser per cycle, fresh context per account.
- Browser-level crash: caught at scheduler; abort current cycle, log ERROR, sleep, restart with fresh browser next cycle.
- Default Playwright timeout: 90s (replaces current 5-minute setting which is excessive).
- Stealth library not bundled in v1 (YAGNI). "URL was rejected" classified as `TransientFetchError`.

### Configuration error handling

- **No accounts configured:** publish App device + INFO log. Loop with no work.
- **Malformed `/data/options.json`:** log FATAL, exit non-zero. Supervisor will loop until user fixes form.
- **Duplicate account usernames:** de-dupe by username, keep first, log WARNING.

### Health surface

`sensor.carriers_sync_app_status` updates each cycle:

| State | When |
|---|---|
| `starting` | Container started, hasn't completed first cycle yet |
| `running` | Last cycle completed (regardless of per-account outcomes) |
| `errored` | Last cycle threw an unhandled exception |

### Out of scope for v1

- Captcha solving / 2FA (adapter raises `AuthFetchError("captcha")`; surfaced for user awareness only)
- Notifications/alerts from the App itself (users wire HA automations off `sync_ok` / `last_synced`)
- Adaptive backoff / rate-limit detection across cycles
- Metrics export (Prometheus/etc.)

## 9. Repository layout, build, testing & release

### Layout

```
carriers-sync/                          # repo root
├── carriers_sync/                      # the App directory (HA scans here)
│   ├── config.yaml
│   ├── Dockerfile
│   ├── run.sh
│   ├── icon.png                           # 128×128
│   ├── logo.png                           # 250×100
│   ├── CHANGELOG.md
│   ├── DOCS.md
│   └── src/
│       └── carriers_sync/
│           ├── __main__.py
│           ├── scheduler.py
│           ├── mqtt_publisher.py
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
│   ├── fixtures/
│   └── conftest.py
├── repository.yaml                        # makes the repo installable as an App store
├── README.md
├── LICENSE
└── .github/workflows/
    ├── ci.yml
    └── release.yml
```

`repository.yaml` declares the repo as a community App store; `carriers_sync/` at repo root is the App directory HA scans.

### Dockerfile migration

Supervisor 2026.04+ removed `build.yaml` and the legacy builder; base images are now multi-arch manifests, so the Dockerfile is plain Docker:

```dockerfile
FROM ghcr.io/home-assistant/base-python:3.12-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Playwright + Chromium (glibc base required)
RUN pip3 install --no-cache-dir playwright \
 && playwright install-deps \
 && playwright install chromium

WORKDIR /app
COPY src/ ./src/
COPY run.sh ./
RUN pip3 install --no-cache-dir -r src/requirements.txt

CMD ["./run.sh"]
```

Changes from current Dockerfile:
- `FROM ubuntu:22.04` → `FROM ghcr.io/home-assistant/base-python:3.12-bookworm` (multi-arch manifest, glibc-based, Python preinstalled).
- Drop `cron`, `supervisor`, `python3`, `python3-pip` apt installs (base image has Python; Supervisor manages process lifecycle).
- Replace `COPY * ./` with explicit `COPY src/ ./src/` + `COPY run.sh ./`.
- Entrypoint: `run.sh` execs `python3 -m carriers_sync`.

Note: pinned image tag (`3.12-bookworm`) intentionally avoids `:latest` so reproducible builds don't break on upstream rebases. Bump deliberately during release work.

### Testing strategy

**Unit tests (the bulk of coverage):**
- **Adapter parser** — fed real anonymised Alfa response fixtures; asserts `ProviderResult` shape. The single most failure-prone piece; isolating it from Playwright lets us update one fixture + one assertion when Alfa changes their JSON.
- **MQTT publisher** — given a `ProviderResult`, asserts discovery payloads, state JSON, topic strings. Mocks the MQTT client.
- **Scheduler** — retry classification, backoff timing (use `freezegun` / async mock clock).
- **State store** — atomic write, round-trip, recovery from corrupt file.
- **Config parser** — valid configs parse to typed dataclasses; invalid raise with useful messages.

Coverage target: 90%+ on `providers/*` and `mqtt_publisher.py`; 70% on `scheduler.py`.

**Integration test (one, optional):** `tests/integration/test_alfa_live.py` hits real Alfa with credentials from env vars. Skipped in CI unless those are set. Manual local sanity check before releases.

**Tools:** `pytest`, `pytest-asyncio`, `freezegun`, `ruff` (lint+format), `mypy --strict`.

### CI (`ci.yml`)

On every push and PR:
1. `ruff check` + `ruff format --check`
2. `mypy --strict src/`
3. `pytest tests/unit/`
4. `docker buildx build --platform linux/amd64` (smoke test that the Dockerfile is valid; multi-arch is release-only)
5. HA `config.yaml` schema validation (lightweight — parse the YAML and check required keys; the legacy validator action is retired)

Target: <3 minutes total.

### Release (`release.yml`)

On git tag `v*`:
1. Run full CI.
2. Multi-arch build with Docker BuildKit (`docker buildx build --platform linux/amd64,linux/arm64`) and push to `ghcr.io/<owner>/carriers-sync:<version>` as a single multi-arch manifest. (The legacy `home-assistant/builder` action was retired in Supervisor 2026.04 — plain BuildKit is now the path.)
3. Update `CHANGELOG.md` from release notes.
4. Bump `version` in `config.yaml` to match tag.
5. Publish GitHub release.

Users see new releases as "Update available" in HA after they've added the repo URL to their App store. No HACS (HACS is for integrations).

### Versioning

- `0.x.y` while the parser stabilises.
- `1.0.0` once the entity model is stable across releases.

### Docs

- `README.md` (repo root) — what this is, install (add repo URL to App store), entity list with screenshots, link to `DOCS.md`.
- `DOCS.md` (in App dir) — shown in App's "Documentation" tab. Field reference, troubleshooting, Alfa quirks, bug-report instructions.
- `CHANGELOG.md` — keep-a-changelog format, shown in App's "Changelog" tab.

### Migration path for existing (Google Keep) users

Two-line note in README: v0.x synced to Google Keep; v1.0+ is a Home Assistant App; no auto-migration; re-enter accounts in the form. Tag current `main` HEAD as `legacy-final` and create a `legacy/google-keep` branch before starting the rewrite.

### Out of scope for v1

- HACS submission (HACS is for integrations)
- Automated visual/screenshot tests
- Load testing
- Telemetry / opt-in metrics

## 10. Open questions / future work

- **Touch (Lebanon) provider** — second adapter; same contract; own Playwright flow. Targeted as v0.2 or v0.3.
- **Ingress status page** — read-only dashboard showing last sync per account, error history, manual refresh buttons. Possible v1.x if user feedback asks.
- **Arabic translations** — `translations/ar.yaml`. Possible v1.x.
- **Captcha handling** — only if Alfa starts gating the login behind one. Likely the project ends if they do.
- **Per-account `provider_options: dict[str, str]`** escape hatch on `AccountConfig` — added when first provider needs it.
