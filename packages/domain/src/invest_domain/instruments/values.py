"""Closed-set value types for the ``instruments`` bounded context."""

from __future__ import annotations

from enum import StrEnum


class InstrumentStatus(StrEnum):
    """Lifecycle status of an instrument.

    Mirrors the ADR-0004 / plan §5.2 ``core.instruments.status`` vocabulary
    but is restricted to the values that the domain can hand to a Provider
    or a storage Repository. ``UNKNOWN`` is the explicit fallback for
    Provider responses that do not disclose lifecycle state.
    """

    ACTIVE = "active"
    SUSPENDED = "suspended"
    DELISTED = "delisted"
    UNKNOWN = "unknown"
