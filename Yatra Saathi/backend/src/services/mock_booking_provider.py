"""Mocked payment/booking provider (section 1, 8, `BOOKING_MODE=mock` only)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from src.core.ids import new_id


@dataclass(frozen=True)
class ProviderResult:
    success: bool
    gateway_reference: Optional[str]
    failure_code: Optional[str] = None


class MockBookingProvider:
    """Always succeeds unless `should_fail` says otherwise (used by tests to
    exercise the rollback / BOOKING_FAILED path)."""

    def __init__(self, should_fail: Optional[Callable[[], bool]] = None):
        self._should_fail = should_fail or (lambda: False)

    def charge(self, *, amount_minor: int, currency: str) -> ProviderResult:
        if self._should_fail():
            return ProviderResult(success=False, gateway_reference=None, failure_code="mock_provider_down")
        return ProviderResult(success=True, gateway_reference=f"mock_{new_id('bkg').split('_', 1)[1]}")
