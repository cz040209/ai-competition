"""Deterministic stand-ins used by the test suite and offline demo mode."""

from __future__ import annotations

import math
from datetime import date

from kira.adapters.protocols import Place, ReceiptRead, VoiceRead
from kira.money import Money

DEMO_DATE = date(2026, 9, 3)

# Places APIs expose a price band, not menu prices. These estimates are curated
# and labelled so the UI cannot imply that a provider returned a real price.
KL_PLACES: tuple[Place, ...] = (
    Place(
        "p1",
        "Nasi Kandar Pelita",
        "Mamak",
        3.1596,
        101.7181,
        Money(1250),
        "high",
        True,
        "Fast counter service, open late.",
    ),
    Place(
        "p2",
        "Zus Coffee, Jln Ampang",
        "Cafe",
        3.1589,
        101.7145,
        Money(900),
        "high",
        True,
        "Coffee and a pastry, not a full meal.",
    ),
    Place(
        "p3",
        "Suria KLCC food court",
        "Food court",
        3.1577,
        101.7120,
        Money(1800),
        "medium",
        True,
        "Widest choice, busiest at 12:30.",
    ),
    Place(
        "p4",
        "Chee Meng Chicken Rice",
        "Chinese",
        3.1571,
        101.7156,
        Money(1600),
        "medium",
        False,
        "Small shop, queue moves quickly.",
    ),
    Place(
        "p5",
        "Nasi Lemak Antarabangsa",
        "Malay",
        3.1652,
        101.7042,
        Money(1100),
        "high",
        True,
        "Kampung Baru institution.",
    ),
    Place(
        "p6",
        "Sushi Zanmai KLCC",
        "Japanese",
        3.1580,
        101.7118,
        Money(4600),
        "low",
        True,
        "Menu prices are not published online.",
    ),
    Place(
        "p7",
        "Lot 10 Hutong",
        "Hawker hall",
        3.1465,
        101.7106,
        Money(2200),
        "medium",
        False,
        "Heritage stalls in one basement.",
    ),
    Place(
        "p8",
        "Village Grocer KLCC",
        "Groceries",
        3.1575,
        101.7124,
        Money(3500),
        "low",
        True,
        "Cook at home instead of eating out.",
    ),
)


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Return great-circle distance for coordinates, where floats are appropriate."""
    radius = 6371.0
    rad = math.pi / 180
    d_lat = (lat2 - lat1) * rad
    d_lng = (lng2 - lng1) * rad
    h = (
        math.sin(d_lat / 2) ** 2
        + math.cos(lat1 * rad) * math.cos(lat2 * rad) * math.sin(d_lng / 2) ** 2
    )
    return 2 * radius * math.asin(math.sqrt(h))


class FakeOcr:
    """Always read the deterministic demo receipt."""

    def read_receipt(self, image: bytes) -> ReceiptRead:
        return ReceiptRead(
            merchant="Nasi Kandar Pelita",
            amount=Money(1890),
            occurred_on=DEMO_DATE,
            confidence=94,
            note="Line item total matched, tax line ignored.",
        )


class FakeVoice:
    def transcribe(self, audio: bytes) -> VoiceRead:
        return VoiceRead(
            transcript="Grab from the office to KLCC, fourteen ringgit",
            merchant="Grab — office to KLCC",
            amount=Money(1400),
            confidence=71,
            note="Heard 'fourteen ringgit'. Amount is worth a second look.",
        )


class FakeMaps:
    def places_near(self, lat: float, lng: float, radius_km: float) -> list[Place]:
        return [
            place
            for place in KL_PLACES
            if haversine_km(lat, lng, place.lat, place.lng) <= radius_km
        ]


class InMemoryStorage:
    def __init__(self) -> None:
        self._blobs: dict[str, bytes] = {}

    def put(self, key: str, data: bytes) -> str:
        self._blobs[key] = data
        return key

    def get(self, key: str) -> bytes:
        return self._blobs[key]


class ScriptedLlm:
    """Replay a fixed script, repeating its last line for longer conversations."""

    def __init__(self, script: list[str]) -> None:
        if not script:
            raise ValueError("ScriptedLlm needs at least one line")
        self._script = list(script)
        self._index = 0

    def complete(self, system: str, messages: list[dict[str, str]]) -> str:
        line = self._script[min(self._index, len(self._script) - 1)]
        self._index += 1
        return line
