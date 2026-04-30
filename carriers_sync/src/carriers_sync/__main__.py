"""Process entrypoint.

Run with: `python -m carriers_sync` (with src/ on PYTHONPATH).

Reads /data/options.json, sets up logging + state store, opens MQTT,
launches Playwright, and runs the scheduler forever.

MQTT connection details:
  - Local dev (docker compose) sets MQTT_HOST/PORT/USERNAME/PASSWORD env vars
    directly. We use those when MQTT_HOST is set.
  - In Home Assistant, declaring services: [mqtt:need] in config.yaml does
    NOT auto-inject env vars; instead Supervisor exposes the broker info at
    GET http://supervisor/services/mqtt with the SUPERVISOR_TOKEN bearer.
    We fall back to that path when MQTT_HOST is unset.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

from playwright.async_api import async_playwright

from carriers_sync.config import AppConfig, ConfigError, load_config
from carriers_sync.logging_setup import configure_logging
from carriers_sync.mqtt_publisher import MqttConfig, MqttPublisher
from carriers_sync.scheduler import Scheduler
from carriers_sync.state_store import StateStore

OPTIONS_PATH = Path("/data/options.json")
STATE_PATH = Path("/data/state.json")


def _mqtt_config() -> MqttConfig:
    """Resolve MQTT connection details.

    Priority:
      1. Explicit MQTT_HOST env var (local dev / docker compose).
      2. Supervisor API at http://supervisor/services/mqtt using
         SUPERVISOR_TOKEN — the standard HA App way.
      3. Fail loudly otherwise.
    """
    if os.environ.get("MQTT_HOST"):
        return MqttConfig(
            host=os.environ["MQTT_HOST"],
            port=int(os.environ.get("MQTT_PORT") or "1883"),
            username=os.environ.get("MQTT_USERNAME") or None,
            password=os.environ.get("MQTT_PASSWORD") or None,
        )

    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        raise RuntimeError(
            "MQTT not configured: set MQTT_HOST (local dev) or run under "
            "HA Supervisor (which sets SUPERVISOR_TOKEN)."
        )

    req = urllib.request.Request(
        "http://supervisor/services/mqtt",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
        raise RuntimeError(
            f"failed to query Supervisor /services/mqtt: {e}. "
            "Make sure the Mosquitto broker App is installed and started."
        ) from e

    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, dict):
        raise RuntimeError(f"unexpected /services/mqtt response shape: {body!r}")

    host = data.get("host")
    port = data.get("port")
    if not host or not port:
        raise RuntimeError(f"Supervisor /services/mqtt did not return host+port: {data!r}")
    return MqttConfig(
        host=str(host),
        port=int(port),
        username=str(data["username"]) if data.get("username") else None,
        password=str(data["password"]) if data.get("password") else None,
    )


def _apply_dev_filter(cfg: AppConfig, log: logging.Logger) -> AppConfig:
    """Optionally narrow `cfg.accounts` to a subset, for fast local iteration.

    Recognised env vars (both optional, comma-separated, AND-combined):

      CARRIERS_SYNC_DEV_PROVIDER   keep accounts whose `provider` matches
                                   one of the listed ids (e.g. "ogero-lb"
                                   or "alfa-lb,touch-lb")
      CARRIERS_SYNC_DEV_USERNAME   keep accounts whose `username` matches
                                   one of the listed values

    Both unset → no filter, all configured accounts run. This intentionally
    does nothing in production: HA Supervisor doesn't set these env vars.
    """
    providers_raw = os.environ.get("CARRIERS_SYNC_DEV_PROVIDER", "").strip()
    usernames_raw = os.environ.get("CARRIERS_SYNC_DEV_USERNAME", "").strip()
    if not providers_raw and not usernames_raw:
        return cfg

    providers = {p.strip() for p in providers_raw.split(",") if p.strip()}
    usernames = {u.strip() for u in usernames_raw.split(",") if u.strip()}

    kept = [
        a
        for a in cfg.accounts
        if (not providers or a.provider in providers) and (not usernames or a.username in usernames)
    ]
    skipped = len(cfg.accounts) - len(kept)
    log.warning(
        "DEV filter active: %d kept, %d skipped (provider=%r username=%r)",
        len(kept),
        skipped,
        providers_raw or "any",
        usernames_raw or "any",
    )
    # AppConfig is frozen — rebuild it.
    return AppConfig(
        poll_interval_minutes=cfg.poll_interval_minutes,
        danger_percent=cfg.danger_percent,
        log_level=cfg.log_level,
        accounts=kept,
    )


async def _amain() -> int:
    try:
        cfg = load_config(OPTIONS_PATH)
    except ConfigError as e:
        print(f"FATAL: invalid /data/options.json: {e}", file=sys.stderr)
        return 1

    secrets = [a.password for a in cfg.accounts if a.password]
    configure_logging(cfg.log_level, secrets=secrets)
    log = logging.getLogger("carriers_sync")

    cfg = _apply_dev_filter(cfg, log)

    log.info("Carriers Sync starting (accounts=%d)", len(cfg.accounts))
    if not cfg.accounts:
        log.info("No accounts configured. Add some in the App's Configuration tab.")

    try:
        mqtt_cfg = _mqtt_config()
    except RuntimeError as e:
        log.error("%s", e)
        return 1
    # Redact the broker password too if we got one from Supervisor.
    if mqtt_cfg.password:
        from carriers_sync.logging_setup import register_secret

        register_secret(mqtt_cfg.password)
    log.info(
        "MQTT broker: %s:%d (auth=%s)",
        mqtt_cfg.host,
        mqtt_cfg.port,
        "yes" if mqtt_cfg.username else "no",
    )

    state_store = StateStore(STATE_PATH)
    publisher = MqttPublisher(mqtt_cfg)

    async with async_playwright() as p:

        async def make_browser():  # type: ignore[no-untyped-def]
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
