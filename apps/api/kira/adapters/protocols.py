"""Narrow, provider-agnostic contracts for every external integration."""

from __future__ import annotations

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
class StorageAdapter(Protocol):
    def put(self, key: str, data: bytes) -> str: ...

    def get(self, key: str) -> bytes: ...


@runtime_checkable
class LlmAdapter(Protocol):
    def complete(self, system: str, messages: list[dict[str, str]]) -> str: ...
