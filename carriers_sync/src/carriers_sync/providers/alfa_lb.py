"""Alfa Lebanon provider adapter.

Split into:
  - parse_response(): pure function, fully unit-tested with fixtures.
  - parse_services(): pure fallback for /account/manage-services/getmyservices.
  - AlfaLbProvider.fetch(): Playwright-driven scrape that calls both.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import UTC, datetime
from typing import Any, ClassVar

from carriers_sync.providers.base import (
    AccountConfig,
    AuthFetchError,
    LineUsage,
    NoConsumptionDataError,
    ProviderResult,
    TransientFetchError,
    UnknownFetchError,
)

logger = logging.getLogger("carriers_sync.providers.alfa_lb")

_SUPPORTED_SERVICES = {"U-share Main", "Mobile Internet"}
_LOGIN_URL = "https://www.alfa.com.lb/en/account/login"
_CONSUMPTION_URL_PATTERN = "**/en/account/getconsumption*"
_GETMYSERVICES_URL = "https://www.alfa.com.lb/en/account/manage-services/getmyservices"
_REJECTED_MARKER = "The requested URL was rejected"
_AUTH_ERROR_MARKERS = (
    "Invalid Username or Password",
    "Account is locked",
    "verification code",
)
_DEFAULT_TIMEOUT_MS = 90_000


def parse_response(
    payload: dict[str, Any],
    *,
    account: AccountConfig,
    fetched_at: datetime,
) -> ProviderResult:
    """Convert Alfa's getconsumption JSON into a ProviderResult.

    Raises UnknownFetchError on any shape mismatch.
    """
    services = payload.get("ServiceInformationValue")
    if not isinstance(services, list) or not services:
        raise UnknownFetchError("missing or empty ServiceInformationValue")

    siv = next(
        (s for s in services if s.get("ServiceNameValue") in _SUPPORTED_SERVICES),
        None,
    )
    if siv is None:
        # Some accounts (alarm SIMs, low-use lines) have a bundle assigned
        # but the consumption endpoint doesn't expose it. The fetcher
        # should fall back to /account/manage-services/getmyservices which
        # always lists the active bundle.
        raise NoConsumptionDataError(
            f"no supported service in getconsumption response (have: "
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


_BUNDLE_TEXT_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(KB|MB|GB|TB)\s*$", re.IGNORECASE)


def parse_services(
    payload: list[dict[str, Any]] | dict[str, Any],
    *,
    account: AccountConfig,
    fetched_at: datetime,
) -> ProviderResult:
    """Parse /account/manage-services/getmyservices and return a placeholder
    ProviderResult based on the active Mobile Internet bundle.

    consumed_gb is 0.0 (this endpoint doesn't expose actual usage). quota_gb
    comes from ActiveBundle.Text — for example '7GB' -> 7.0. If no active
    bundle (or PAYG / unparseable), returns a no-plan placeholder.
    """
    if not isinstance(payload, list):
        raise UnknownFetchError("getmyservices response is not a JSON array")

    mi = next(
        (s for s in payload if isinstance(s, dict) and s.get("Name") == "Mobile Internet"), None
    )
    if mi is None:
        return _no_plan_result(account, fetched_at)

    active = mi.get("ActiveBundle")
    if not isinstance(active, dict) or not active.get("Selected"):
        return _no_plan_result(account, fetched_at)

    text = active.get("TextEn") or active.get("Text") or ""
    quota_gb = _parse_bundle_text(str(text))
    if quota_gb is None:
        # PAYG or non-volumetric bundle — treat as no-plan
        logger.info(
            "%s active Mobile Internet bundle is non-volumetric (%r); reporting as no-plan",
            account.username,
            text,
        )
        return _no_plan_result(account, fetched_at)

    return ProviderResult(
        account_id=account.username,
        lines=[
            LineUsage(
                line_id=account.username,
                label=account.label or account.username,
                consumed_gb=0.0,
                quota_gb=quota_gb,
                extra_consumed_gb=0.0,
                is_secondary=False,
                parent_line_id=None,
            )
        ],
        fetched_at=fetched_at,
    )


def _parse_bundle_text(text: str) -> float | None:
    """Parse Alfa's bundle Text field. '7GB' -> 7.0, '475GB' -> 475.0,
    '10MB' -> 0.01. Returns None for 'PAYG' or unrecognised formats."""
    m = _BUNDLE_TEXT_RE.match(text)
    if not m:
        return None
    try:
        return _to_gb(float(m.group(1)), m.group(2).upper())
    except UnknownFetchError:
        return None


def _no_plan_result(account: AccountConfig, fetched_at: datetime) -> ProviderResult:
    return ProviderResult(
        account_id=account.username,
        lines=[
            LineUsage(
                line_id=account.username,
                label=account.label or account.username,
                consumed_gb=0.0,
                quota_gb=None,
                extra_consumed_gb=0.0,
                is_secondary=False,
                parent_line_id=None,
            )
        ],
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
                # Async API: info.value is awaitable; sync API would expose it
                # as a plain attribute. We're async — await it.
                response = await info.value
            except (AuthFetchError, TransientFetchError, UnknownFetchError):
                raise
            except TimeoutError as e:
                raise TransientFetchError("getconsumption XHR did not arrive") from e
            except Exception as e:
                raise TransientFetchError(f"waiting for getconsumption failed: {e}") from e

            payload = await response.json()
            now = datetime.now(UTC)
            try:
                return parse_response(payload, account=account, fetched_at=now)
            except NoConsumptionDataError as e:
                logger.info(
                    "%s: %s — falling back to getmyservices for active bundle",
                    account.username,
                    e,
                )
                return await self._fetch_via_services(context, account, fetched_at=now)
        finally:
            await context.close()

    @staticmethod
    async def _fetch_via_services(
        context: Any, account: AccountConfig, *, fetched_at: datetime
    ) -> ProviderResult:
        """Hit /account/manage-services/getmyservices using the post-login
        cookies in `context`. Used as a fallback when getconsumption has no
        Mobile Internet for the account.
        """
        url = f"{_GETMYSERVICES_URL}?_={int(time.time() * 1000)}"
        try:
            resp = await context.request.get(
                url,
                headers={
                    "X-Requested-With": "XMLHttpRequest",
                    "Accept": "application/json, text/javascript, */*; q=0.01",
                },
            )
        except Exception as e:
            raise TransientFetchError(f"getmyservices request failed: {e}") from e
        if not resp.ok:
            raise TransientFetchError(f"getmyservices HTTP {resp.status}")
        payload = await resp.json()
        return parse_services(payload, account=account, fetched_at=fetched_at)

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
