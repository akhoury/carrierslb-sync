"""Provider registry: maps provider id strings to adapter classes."""

from __future__ import annotations

from carriers_sync.providers.alfa_lb import AlfaLbProvider
from carriers_sync.providers.base import Provider
from carriers_sync.providers.ogero_lb import OgeroLbProvider
from carriers_sync.providers.touch_lb import TouchLbProvider

PROVIDERS: dict[str, type[Provider]] = {
    AlfaLbProvider.id: AlfaLbProvider,
    TouchLbProvider.id: TouchLbProvider,
    OgeroLbProvider.id: OgeroLbProvider,
}


def get_provider(provider_id: str) -> Provider:
    try:
        cls = PROVIDERS[provider_id]
    except KeyError as e:
        raise KeyError(f"unknown provider id: {provider_id}") from e
    return cls()
