"""One place that chooses the implementation for each adapter."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from kira.adapters.fakes import FakeMaps, FakeOcr, FakeVoice, InMemoryStorage, ScriptedLlm
from kira.adapters.protocols import (
    LlmAdapter,
    MapsAdapter,
    OcrAdapter,
    StorageAdapter,
    VoiceAdapter,
)


@dataclass(frozen=True, slots=True)
class Adapters:
    ocr: OcrAdapter
    voice: VoiceAdapter
    maps: MapsAdapter
    storage: StorageAdapter
    llm: LlmAdapter


@lru_cache
def get_adapters() -> Adapters:
    """Use offline fakes until real providers are deliberately configured."""
    return Adapters(
        ocr=FakeOcr(),
        voice=FakeVoice(),
        maps=FakeMaps(),
        storage=InMemoryStorage(),
        llm=ScriptedLlm(["I can only answer from what you have confirmed."]),
    )
