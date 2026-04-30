from datetime import UTC, datetime

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
        fetched_at=datetime(2026, 4, 28, 12, 0, tzinfo=UTC),
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


def test_atomic_write_no_leftover_tmp(tmp_path):
    target = tmp_path / "state.json"
    store = StateStore(target)
    store.save(State(last_results={"03333333": make_result()}, last_published_entities=set()))
    assert not (tmp_path / "state.json.tmp").exists()
    assert target.exists()


def test_corrupt_file_recovers_with_warning(tmp_path, caplog):
    import logging

    target = tmp_path / "state.json"
    target.write_text("{this is not json")
    store = StateStore(target)
    with caplog.at_level(logging.WARNING):
        state = store.load()
    assert state.last_results == {}
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
        fetched_at=datetime(2026, 4, 28, tzinfo=UTC),
    )
    store.save(State(last_results={"03333333": res}, last_published_entities=set()))
    loaded = store.load()
    assert loaded.last_results["03333333"].lines[0].label == "جون"
