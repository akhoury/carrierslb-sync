"""Long-lived MQTT connection used to publish discovery + state messages
and to receive button-press commands. Wraps aiomqtt.Client.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from types import TracebackType

from aiomqtt import Client, Will

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

    async def __aenter__(self) -> MqttPublisher:
        will = Will(
            topic=AVAILABILITY_TOPIC,
            payload="offline",
            qos=1,
            retain=True,
        )
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

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._client is None:
            return
        try:
            await self._client.publish(AVAILABILITY_TOPIC, "offline", qos=1, retain=True)
        finally:
            await self._client.__aexit__(exc_type, exc, tb)
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
        # Single wildcard subscription matches all provider/account refresh
        # buttons — `carriers_sync/<provider>/<account>/refresh/cmd`. The
        # account_ids parameter is retained for compatibility but no longer
        # needed to enumerate per-account topics.
        assert self._client is not None
        del account_ids  # unused; kept for API stability
        await self._client.subscribe("carriers_sync/refresh_all/cmd")
        await self._client.subscribe("carriers_sync/+/+/refresh/cmd")

    async def commands(self) -> AsyncIterator[RefreshCommand]:
        assert self._client is not None
        async for msg in self._client.messages:
            topic = msg.topic.value
            if topic == "carriers_sync/refresh_all/cmd":
                yield RefreshCommand(account_id=None)
                continue
            # `carriers_sync/<provider>/<account>/refresh/cmd`
            parts = topic.split("/")
            if (
                len(parts) == 5
                and parts[0] == "carriers_sync"
                and parts[3] == "refresh"
                and parts[4] == "cmd"
            ):
                yield RefreshCommand(account_id=parts[2])
            else:
                logger.warning("ignoring unexpected command topic: %s", topic)
