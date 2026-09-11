from pathlib import Path
from types import SimpleNamespace

import pytest

from src.support.clients.transcription.transcription_client import TranscriptionClient


class FakeTranscriptions:
    def __init__(self, payload):
        self._payload = payload
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._payload


def fake_openai(payload):
    return SimpleNamespace(audio=SimpleNamespace(transcriptions=FakeTranscriptions(payload)))


@pytest.mark.asyncio
async def test_maps_segments_to_domain_objects(tmp_path: Path):
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"fake")
    payload = SimpleNamespace(segments=[
        SimpleNamespace(text=" olá ", start=0.0, end=2.5),
        SimpleNamespace(text="tokens", start=2.5, end=5.0),
    ])
    client = TranscriptionClient(openai_client=fake_openai(payload))

    segments = await client.transcribe(audio, prompt="Tokens, embeddings")

    assert [s.text for s in segments] == ["olá", "tokens"]
    assert segments[1].start == 2.5 and segments[1].end == 5.0


@pytest.mark.asyncio
async def test_sends_the_glossary_prompt_and_the_language(tmp_path: Path):
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"fake")
    openai = fake_openai(SimpleNamespace(segments=[]))
    client = TranscriptionClient(openai_client=openai)

    await client.transcribe(audio, prompt="autorregressão, tokenização")

    call = openai.audio.transcriptions.calls[0]
    assert call["prompt"] == "autorregressão, tokenização"
    assert call["language"] == "pt"
    assert call["response_format"] == "verbose_json"


@pytest.mark.asyncio
async def test_a_response_without_segments_yields_an_empty_list(tmp_path: Path):
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"fake")
    client = TranscriptionClient(openai_client=fake_openai(SimpleNamespace(segments=None)))
    assert await client.transcribe(audio, prompt="") == []
