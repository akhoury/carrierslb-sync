from datetime import UTC, datetime

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
    with pytest.raises((AttributeError, TypeError)):
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
    now = datetime(2026, 4, 28, 12, 0, tzinfo=UTC)
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


def test_provider_protocol_declares_required_attrs():
    # Protocol attributes are declared via annotations, not as real class
    # attributes; check the annotation set.
    annotations = Provider.__annotations__
    assert "id" in annotations
    assert "display_name" in annotations
    # fetch is a method, not an annotation; verify it's defined.
    assert callable(Provider.fetch)
