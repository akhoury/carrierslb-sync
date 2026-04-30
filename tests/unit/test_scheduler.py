"""Tests for the scheduler: retry classification, backoff, refresh events,
and cycle behavior."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

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
                line_id="03333333",
                label="John",
                consumed_gb=1.0,
                quota_gb=20.0,
                extra_consumed_gb=0.0,
                is_secondary=False,
                parent_line_id=None,
            )
        ],
        fetched_at=datetime(2026, 4, 28, tzinfo=UTC),
    )


def test_classify_outcome_maps_exceptions_to_short_tokens():
    assert classify_outcome(None) == ""
    assert classify_outcome(TransientFetchError("x")) == "transient"
    assert classify_outcome(AuthFetchError("x")) == "auth"
    assert classify_outcome(UnknownFetchError("x")) == "unknown"
    assert classify_outcome(TimeoutError()) == "timeout"
    assert classify_outcome(RuntimeError("?")) == "unknown"


async def test_run_one_account_success_returns_result():
    provider = MagicMock()
    provider.fetch = AsyncMock(return_value=make_result())
    policy = RetryPolicy(transient_backoffs=(0.0, 0.0, 0.0))
    result, err = await run_one_account(provider, make_account(), MagicMock(), policy)
    assert err is None
    assert result is not None
    provider.fetch.assert_awaited_once()


async def test_run_one_account_transient_retries_then_succeeds():
    provider = MagicMock()
    provider.fetch = AsyncMock(side_effect=[TransientFetchError("first"), make_result()])
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
    assert provider.fetch.await_count == 2


async def test_cycle_iterates_all_accounts_and_publishes(monkeypatch):
    """Run a single cycle: scheduler fetches each account, builds messages,
    asks the publisher to publish them."""
    from carriers_sync.scheduler import Scheduler

    provider = MagicMock()
    provider.fetch = AsyncMock(return_value=make_result())
    monkeypatch.setattr("carriers_sync.scheduler.get_provider", lambda _: provider)

    publisher = MagicMock()
    publisher.publish_many = AsyncMock()
    publisher.subscribe_commands = AsyncMock()

    state_store = MagicMock()
    state_store.load = MagicMock(
        return_value=MagicMock(last_results={}, last_published_entities=set())
    )
    state_store.save = MagicMock()

    fake_browser = MagicMock()
    fake_browser.close = AsyncMock()

    async def browser_factory():
        return fake_browser

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
