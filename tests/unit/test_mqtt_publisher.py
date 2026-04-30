"""Verify the MQTT publisher's connection lifecycle, LWT, and command-topic dispatch."""

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

    async def _empty():
        if False:
            yield None
        return

    instance.messages = _empty()

    factory = MagicMock(return_value=instance)
    monkeypatch.setattr("carriers_sync.mqtt_publisher.Client", factory)
    return instance, factory


async def test_publishes_message(fake_client):
    instance, _ = fake_client
    cfg = MqttConfig(host="h", port=1883, username=None, password=None)
    pub = MqttPublisher(cfg)
    async with pub:
        await pub.publish_many(
            [
                MqttMessage(topic="t/1", payload={"a": 1}, retain=True),
                MqttMessage(topic="t/2", payload="raw", retain=False),
            ]
        )
    calls = instance.publish.await_args_list
    publish_topics = [c.args[0] for c in calls]
    assert "carriers_sync/availability" in publish_topics  # connect-time online
    assert "t/1" in publish_topics
    assert "t/2" in publish_topics


async def test_lwt_set_on_connect(fake_client):
    _, factory = fake_client
    cfg = MqttConfig(host="h", port=1883, username=None, password=None)
    pub = MqttPublisher(cfg)
    async with pub:
        pass
    will = factory.call_args.kwargs["will"]
    assert will.topic == "carriers_sync/availability"
    assert will.payload == "offline"
    assert will.retain is True


async def test_subscribes_to_command_topics(fake_client):
    """Subscriptions are wildcard-based to cover all provider/account combos
    (carriers_sync/<provider>/<account>/refresh/cmd) plus the singleton
    refresh-all topic."""
    instance, _ = fake_client
    cfg = MqttConfig(host="h", port=1883, username=None, password=None)
    pub = MqttPublisher(cfg)
    async with pub:
        await pub.subscribe_commands(account_ids=["03333333", "03222222"])
    instance.subscribe.assert_any_await("carriers_sync/refresh_all/cmd")
    instance.subscribe.assert_any_await("carriers_sync/+/+/refresh/cmd")


async def test_command_iterator_yields_refresh_objects(fake_client):
    instance, _ = fake_client

    msg1 = MagicMock()
    msg1.topic = MagicMock()
    msg1.topic.value = "carriers_sync/refresh_all/cmd"
    msg2 = MagicMock()
    msg2.topic = MagicMock()
    msg2.topic.value = "carriers_sync/alfa_lb/03333333/refresh/cmd"
    msg3 = MagicMock()
    msg3.topic = MagicMock()
    msg3.topic.value = "carriers_sync/touch_lb/familyacct/refresh/cmd"

    async def _gen():
        yield msg1
        yield msg2
        yield msg3

    instance.messages = _gen()

    cfg = MqttConfig(host="h", port=1883, username=None, password=None)
    pub = MqttPublisher(cfg)
    async with pub:
        commands = []
        async for cmd in pub.commands():
            commands.append(cmd)
            if len(commands) == 3:
                break
    assert commands[0] == RefreshCommand(account_id=None)
    assert commands[1] == RefreshCommand(account_id="03333333")
    assert commands[2] == RefreshCommand(account_id="familyacct")
