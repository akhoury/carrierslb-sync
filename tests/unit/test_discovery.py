from datetime import UTC, datetime

import pytest
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
        fetched_at=datetime(2026, 4, 28, 12, 0, tzinfo=UTC),
    )


def _build(result, **overrides):
    """Default test invocation of build_account_messages with sensible defaults."""
    kwargs = {
        "danger_percent": 80,
        "provider_display": "Alfa (Lebanon)",
        "provider_id": "alfa-lb",
    }
    kwargs.update(overrides)
    return build_account_messages(result, **kwargs)


def test_app_device_messages_include_refresh_all_button_and_status_sensor():
    msgs = build_app_device_messages()
    topics = [m.topic for m in msgs]
    assert any("button/carriers_sync_refresh_all/config" in t for t in topics)
    assert any("sensor/carriers_sync_app_status/config" in t for t in topics)


def test_account_discovery_publishes_main_and_secondary_devices():
    result = make_result_ushare()
    msgs = _build(result)
    topics = {m.topic for m in msgs}

    assert "homeassistant/sensor/carriers_sync_alfa_lb_03333333_consumed_gb/config" in topics
    assert "homeassistant/sensor/carriers_sync_alfa_lb_03333333_quota_gb/config" in topics
    assert "homeassistant/sensor/carriers_sync_alfa_lb_03333333_total_consumed_gb/config" in topics
    assert "homeassistant/binary_sensor/carriers_sync_alfa_lb_03333333_danger/config" in topics
    assert "homeassistant/button/carriers_sync_alfa_lb_03333333_refresh/config" in topics
    assert "homeassistant/sensor/carriers_sync_alfa_lb_03222222_consumed_gb/config" in topics


def test_state_payload_includes_total_and_percent():
    result = make_result_ushare()
    msgs = _build(result)
    state_msg = next(m for m in msgs if m.topic == "carriers_sync/alfa_lb/03333333/state")
    payload = state_msg.payload
    assert payload["consumed_gb"] == 2.0
    assert payload["total_consumed_gb"] == 3.0
    assert payload["quota_gb"] == 20.0
    assert payload["remaining_gb"] == 17.0
    assert payload["usage_percent"] == 15.0
    assert payload["sync_ok"] == "ON"
    assert payload["danger"] == "OFF"
    assert payload["last_synced"] == "2026-04-28T12:00:00+00:00"
    assert payload["last_attempted"] == "2026-04-28T12:00:00+00:00"
    assert payload["last_error"] == ""


def test_danger_flag_when_usage_over_threshold():
    result = ProviderResult(
        account_id="03333333",
        lines=[
            LineUsage(
                line_id="03333333",
                label="John",
                consumed_gb=18.0,
                quota_gb=20.0,
                extra_consumed_gb=0.0,
                is_secondary=False,
                parent_line_id=None,
            ),
        ],
        fetched_at=datetime(2026, 4, 28, tzinfo=UTC),
    )
    msgs = _build(result)
    state = next(m for m in msgs if m.topic.endswith("03333333/state"))
    assert state.payload["danger"] == "ON"


def test_danger_flag_when_extra_consumed_positive():
    result = ProviderResult(
        account_id="03333333",
        lines=[
            LineUsage(
                line_id="03333333",
                label="John",
                consumed_gb=1.0,
                quota_gb=20.0,
                extra_consumed_gb=0.5,
                is_secondary=False,
                parent_line_id=None,
            ),
        ],
        fetched_at=datetime(2026, 4, 28, tzinfo=UTC),
    )
    msgs = _build(result)
    state = next(m for m in msgs if m.topic.endswith("03333333/state"))
    assert state.payload["danger"] == "ON"


def test_secondary_state_topic_distinct_from_main():
    result = make_result_ushare()
    msgs = _build(result)
    sec_state = next(m for m in msgs if m.topic == "carriers_sync/alfa_lb/03333333/03222222/state")
    assert sec_state.payload["consumed_gb"] == 1.0


def test_aggregate_main_does_not_double_count_secondaries():
    """Touch-style result: synthetic aggregate main where consumed_gb already
    rolls up secondaries' usage. Discovery must not sum secondaries again."""
    result = ProviderResult(
        account_id="familyacct",
        lines=[
            LineUsage(
                line_id="familyacct",
                label="Touch Account",
                consumed_gb=4.0,  # already = sum of secondaries
                quota_gb=32.0,  # already = sum of secondaries' quotas
                extra_consumed_gb=0.0,
                is_secondary=False,
                parent_line_id=None,
                is_aggregate=True,
            ),
            LineUsage(
                line_id="81111111",
                label="Number 1",
                consumed_gb=1.0,
                quota_gb=25.0,
                extra_consumed_gb=0.0,
                is_secondary=True,
                parent_line_id="familyacct",
            ),
            LineUsage(
                line_id="81222222",
                label="Number 2",
                consumed_gb=3.0,
                quota_gb=7.0,
                extra_consumed_gb=0.0,
                is_secondary=True,
                parent_line_id="familyacct",
            ),
        ],
        fetched_at=datetime(2026, 4, 28, tzinfo=UTC),
    )
    msgs = _build(result, provider_display="Touch (Lebanon)", provider_id="touch-lb")
    main_state = next(m for m in msgs if m.topic == "carriers_sync/touch_lb/familyacct/state")
    # If we double-counted we'd see total_consumed_gb=8.0 (= 4 + 1 + 3).
    assert main_state.payload["total_consumed_gb"] == 4.0
    assert main_state.payload["consumed_gb"] == 4.0
    assert main_state.payload["quota_gb"] == 32.0


def test_secondary_with_own_quota_publishes_full_sensor_set():
    """Touch-style secondary: has its own quota_gb. Discovery should emit
    quota/remaining/usage_percent/danger sensors for it (not just consumed)."""
    result = ProviderResult(
        account_id="familyacct",
        lines=[
            LineUsage(
                line_id="familyacct",
                label="Touch",
                consumed_gb=2.77,
                quota_gb=7.0,
                extra_consumed_gb=0.0,
                is_secondary=False,
                parent_line_id=None,
                is_aggregate=True,
            ),
            LineUsage(
                line_id="81222222",
                label="Stephanie",
                consumed_gb=2.77,
                quota_gb=7.0,
                extra_consumed_gb=0.0,
                is_secondary=True,
                parent_line_id="familyacct",
            ),
        ],
        fetched_at=datetime(2026, 4, 28, tzinfo=UTC),
    )
    msgs = _build(result, provider_display="Touch (Lebanon)", provider_id="touch-lb")
    topics = {m.topic for m in msgs}
    assert "homeassistant/sensor/carriers_sync_touch_lb_81222222_quota_gb/config" in topics
    assert "homeassistant/sensor/carriers_sync_touch_lb_81222222_remaining_gb/config" in topics
    assert "homeassistant/sensor/carriers_sync_touch_lb_81222222_usage_percent/config" in topics
    assert "homeassistant/binary_sensor/carriers_sync_touch_lb_81222222_danger/config" in topics

    sec_state = next(
        m for m in msgs if m.topic == "carriers_sync/touch_lb/familyacct/81222222/state"
    )
    assert sec_state.payload["consumed_gb"] == pytest.approx(2.77)
    assert sec_state.payload["quota_gb"] == pytest.approx(7.0)
    assert sec_state.payload["remaining_gb"] == pytest.approx(4.23)
    assert sec_state.payload["usage_percent"] == pytest.approx(39.6, rel=0.01)
    assert sec_state.payload["danger"] == "OFF"


def test_alfa_secondary_without_own_quota_publishes_only_consumed():
    """Alfa twin secondaries have quota_gb=None. Discovery should emit only
    consumed_gb — no quota/remaining sensors (those would be misleading)."""
    result = make_result_ushare()  # twins have quota_gb=None
    msgs = _build(result)
    topics = {m.topic for m in msgs}
    # No quota sensor for the Alfa twin
    assert "homeassistant/sensor/carriers_sync_alfa_lb_03222222_quota_gb/config" not in topics
    # Just consumed_gb
    assert "homeassistant/sensor/carriers_sync_alfa_lb_03222222_consumed_gb/config" in topics


def test_unique_id_includes_provider_qualifier():
    """The provider qualifier must appear in unique_id, object_id, and the
    device identifier so that two providers with overlapping line_ids would
    not collide."""
    result = make_result_ushare()
    msgs = _build(result)
    config = next(
        m
        for m in msgs
        if m.topic == "homeassistant/sensor/carriers_sync_alfa_lb_03333333_consumed_gb/config"
    )
    assert config.payload["unique_id"] == "carriers_sync_alfa_lb_03333333_consumed_gb"
    assert config.payload["object_id"] == "carriers_sync_alfa_lb_03333333_consumed_gb"
    assert config.payload["device"]["identifiers"] == ["carriers_sync_alfa_lb_03333333"]
