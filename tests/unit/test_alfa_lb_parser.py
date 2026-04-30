import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from carriers_sync.providers.alfa_lb import parse_response, parse_services
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
    fetched_at = datetime(2026, 4, 28, 12, 0, tzinfo=UTC)
    result = parse_response(payload, account=make_account(), fetched_at=fetched_at)

    assert result.account_id == "03333333"
    assert result.fetched_at == fetched_at
    assert len(result.lines) == 3

    main = result.lines[0]
    assert main.line_id == "03333333"
    assert main.label == "John"
    assert main.is_secondary is False
    assert main.consumed_gb == pytest.approx(2.0)
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
        fetched_at=datetime.now(UTC),
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
        account=make_account(secondary_labels={"03222222": "Wife"}),
        fetched_at=datetime.now(UTC),
    )
    sec_unlabelled = next(line for line in result.lines if line.line_id == "03111111")
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
        fetched_at=datetime.now(UTC),
    )
    assert result.lines[0].extra_consumed_gb == pytest.approx(1.5)


def test_missing_service_information_raises_unknown():
    with pytest.raises(UnknownFetchError):
        parse_response(
            {},
            account=make_account(secondary_labels={}),
            fetched_at=datetime.now(UTC),
        )


def test_no_supported_service_raises_no_consumption_data_error():
    """Alarm SIMs / voice-only lines often have no Mobile Internet entry in
    getconsumption. We raise a specific subclass so the fetcher can fall
    back to getmyservices."""
    from carriers_sync.providers.base import NoConsumptionDataError

    payload = {
        "ServiceInformationValue": [
            {"ServiceNameValue": "Voice", "ServiceDetailsInformationValue": []}
        ]
    }
    with pytest.raises(NoConsumptionDataError, match="no supported service"):
        parse_response(
            payload,
            account=make_account(secondary_labels={}),
            fetched_at=datetime.now(UTC),
        )


def test_parse_services_finds_active_mobile_internet_bundle():
    payload = json.loads((FIXTURES / "alfa_getmyservices_response.json").read_text())
    result = parse_services(
        payload,
        account=make_account(secondary_labels={}),
        fetched_at=datetime(2026, 4, 28, tzinfo=UTC),
    )
    assert len(result.lines) == 1
    main = result.lines[0]
    assert main.line_id == "03333333"
    assert main.consumed_gb == 0.0  # endpoint doesn't expose usage
    assert main.quota_gb == pytest.approx(7.0)
    assert main.is_secondary is False


def test_parse_services_no_mobile_internet_returns_no_plan():
    payload = [
        {"Name": "CLIP", "ActiveBundle": None},
        {"Name": "Detailed Bill", "ActiveBundle": None},
    ]
    result = parse_services(
        payload,
        account=make_account(secondary_labels={}),
        fetched_at=datetime.now(UTC),
    )
    main = result.lines[0]
    assert main.consumed_gb == 0.0
    assert main.quota_gb is None  # signals no plan


def test_parse_services_active_but_payg_returns_no_plan():
    payload = [
        {
            "Name": "Mobile Internet",
            "ActiveBundle": {
                "Text": "PAYG",
                "TextEn": "PAYG",
                "Selected": True,
            },
        }
    ]
    result = parse_services(
        payload,
        account=make_account(secondary_labels={}),
        fetched_at=datetime.now(UTC),
    )
    assert result.lines[0].quota_gb is None


def test_parse_services_active_but_unselected_returns_no_plan():
    payload = [
        {
            "Name": "Mobile Internet",
            "ActiveBundle": {"Text": "7GB", "TextEn": "7GB", "Selected": False},
        }
    ]
    result = parse_services(
        payload,
        account=make_account(secondary_labels={}),
        fetched_at=datetime.now(UTC),
    )
    assert result.lines[0].quota_gb is None


def test_parse_services_handles_mb_units():
    payload = [
        {
            "Name": "Mobile Internet",
            "ActiveBundle": {"Text": "500MB", "TextEn": "500MB", "Selected": True},
        }
    ]
    result = parse_services(
        payload,
        account=make_account(secondary_labels={}),
        fetched_at=datetime.now(UTC),
    )
    assert result.lines[0].quota_gb == pytest.approx(500 / 1024, abs=0.001)


def test_parse_services_invalid_payload_raises_unknown():
    with pytest.raises(UnknownFetchError, match="not a JSON array"):
        parse_services(
            {"not": "a list"},
            account=make_account(secondary_labels={}),
            fetched_at=datetime.now(UTC),
        )
