"""One place that chooses the implementation for each adapter."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from kira.adapters.fakes import (
    FakeMaps,
    FakeOcr,
    FakeVoice,
    InMemoryStorage,
    NoRouting,
    ScriptedLlm,
)
from kira.adapters.osrm import OsrmRouting
from kira.adapters.protocols import (
    LlmAdapter,
    MapsAdapter,
    OcrAdapter,
    RoutingAdapter,
    StorageAdapter,
    VoiceAdapter,
)
from kira.config import get_settings


@dataclass(frozen=True, slots=True)
class Adapters:
    ocr: OcrAdapter
    voice: VoiceAdapter
    maps: MapsAdapter
    routing: RoutingAdapter
    storage: StorageAdapter
    llm: LlmAdapter


def straight_line_reason() -> str | None:
    """Why distances would be straight-line right now, or None if they would not.

    The same shape as the Butler's ``offline_reason``: the degraded path is a
    named state with a stated cause, not a boolean buried inside a factory. A
    reason here means no request is even attempted -- an unreachable router is
    the *other* way this ends up on the straight line, and that one is decided
    per call inside ``OsrmRouting``.
    """
    settings = get_settings()
    if not settings.routing_enabled:
        return "ROUTING_ENABLED is off"
    if not settings.osrm_base_url.strip():
        return "no OSRM base URL is configured"
    return None


def choose_routing() -> RoutingAdapter:
    if straight_line_reason() is not None:
        return NoRouting()
    settings = get_settings()
    return OsrmRouting(settings.osrm_base_url, settings.routing_timeout_seconds)


@lru_cache
def get_adapters() -> Adapters:
    """Use offline fakes until real providers are deliberately configured."""
    return Adapters(
        ocr=FakeOcr(),
        voice=FakeVoice(),
        maps=FakeMaps(),
        routing=choose_routing(),
        storage=InMemoryStorage(),
        llm=ScriptedLlm(["I can only answer from what you have confirmed."]),
    )
