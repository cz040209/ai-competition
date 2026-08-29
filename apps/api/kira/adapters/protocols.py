"""Narrow, provider-agnostic contracts for every external integration."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Protocol, runtime_checkable

from kira.money import Money


@dataclass(frozen=True, slots=True)
class ReceiptRead:
    merchant: str
    amount: Money
    occurred_on: date
    confidence: int
    note: str


@dataclass(frozen=True, slots=True)
class VoiceRead:
    transcript: str
    merchant: str
    amount: Money
    confidence: int
    note: str


@dataclass(frozen=True, slots=True)
class Place:
    id: str
    name: str
    kind: str
    lat: float
    lng: float
    estimate: Money
    confidence: str
    halal: bool
    note: str
    # Where it actually is, in words. A place named on a screen that quotes a
    # fare to get there has to be findable, and coordinates are not an address.
    # Defaulted so the small worlds the tests build stay readable.
    address: str = ""


@runtime_checkable
class OcrAdapter(Protocol):
    def read_receipt(self, image: bytes) -> ReceiptRead: ...


@runtime_checkable
class VoiceAdapter(Protocol):
    def transcribe(self, audio: bytes) -> VoiceRead: ...


@runtime_checkable
class MapsAdapter(Protocol):
    def places_near(self, lat: float, lng: float, radius_km: float) -> list[Place]: ...


@runtime_checkable
class RoutingAdapter(Protocol):
    """Distance along the roads, which is the only distance a fare is charged on.

    One origin, many destinations, one call: the planner asks about every
    candidate it is going to price at once, because a per-place round trip to a
    router is a page that loads at the speed of the slowest one.

    The answer is one entry per destination, in the order they were given, and
    ``None`` wherever this destination could not be routed. An answer that is
    all ``None`` is the router saying nothing at all -- off, unreachable, or
    refusing -- and the caller falls back to the straight line and says so. It
    is a normal state, not an error: implementations do not raise.
    """

    async def road_metres(
        self, origin: tuple[float, float], destinations: Sequence[tuple[float, float]]
    ) -> list[float | None]: ...


@runtime_checkable
class StorageAdapter(Protocol):
    def put(self, key: str, data: bytes) -> str: ...

    def get(self, key: str) -> bytes: ...


@runtime_checkable
class LlmAdapter(Protocol):
    def complete(self, system: str, messages: list[dict[str, str]]) -> str: ...
