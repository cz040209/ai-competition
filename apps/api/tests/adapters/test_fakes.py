from datetime import date

from kira.adapters.fakes import FakeMaps, FakeOcr, FakeVoice, InMemoryStorage, ScriptedLlm
from kira.adapters.protocols import (
    LlmAdapter,
    MapsAdapter,
    OcrAdapter,
    StorageAdapter,
    VoiceAdapter,
)
from kira.adapters.registry import get_adapters
from kira.money import Money


class TestProtocolConformance:
    def test_every_fake_satisfies_its_protocol(self):
        assert isinstance(FakeOcr(), OcrAdapter)
        assert isinstance(FakeVoice(), VoiceAdapter)
        assert isinstance(FakeMaps(), MapsAdapter)
        assert isinstance(InMemoryStorage(), StorageAdapter)
        assert isinstance(ScriptedLlm(["hello"]), LlmAdapter)


class TestFakeOcr:
    def test_reads_the_demo_receipt_deterministically(self):
        first = FakeOcr().read_receipt(b"any bytes")
        second = FakeOcr().read_receipt(b"different bytes")
        assert first == second
        assert first.merchant == "Nasi Kandar Pelita"
        assert first.amount == Money(1890)
        assert first.confidence == 94
        assert isinstance(first.occurred_on, date)


class TestFakeVoice:
    def test_returns_the_demo_transcript(self):
        read = FakeVoice().transcribe(b"audio")
        assert read.amount == Money(1400)
        assert read.confidence == 71
        assert "fourteen" in read.transcript.lower()


class TestFakeMaps:
    def test_returns_the_curated_kl_set(self):
        places = FakeMaps().places_near(3.1577, 101.7120, 3.0)
        assert len(places) == 8
        assert places[0].name == "Nasi Kandar Pelita"
        assert places[0].estimate == Money(1250)
        assert {place.confidence for place in places} <= {"high", "medium", "low"}

    def test_radius_filters(self):
        near = FakeMaps().places_near(3.1577, 101.7120, 0.5)
        assert 0 < len(near) < 8


class TestInMemoryStorage:
    def test_round_trips_bytes(self):
        storage = InMemoryStorage()
        key = storage.put("receipts/1.jpg", b"\xff\xd8\xff")
        assert storage.get(key) == b"\xff\xd8\xff"


class TestScriptedLlm:
    def test_replays_its_script_in_order(self):
        llm = ScriptedLlm(["one", "two"])
        assert llm.complete("s", []) == "one"
        assert llm.complete("s", []) == "two"
        assert llm.complete("s", []) == "two"


class TestRegistry:
    def test_defaults_to_fakes(self):
        adapters = get_adapters()
        assert isinstance(adapters.ocr, FakeOcr)
        assert isinstance(adapters.maps, FakeMaps)
