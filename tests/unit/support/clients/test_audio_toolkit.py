import asyncio
from pathlib import Path

import pytest

from src.support.clients.transcription.audio_toolkit import AudioProcessingError, AudioToolkit
from src.support.core.settings import settings


def test_short_audio_is_a_single_window():
    assert AudioToolkit.plan_segments(duration=120.0, window=600) == [(0.0, 120.0)]


def test_exact_multiple_does_not_produce_an_empty_tail():
    assert AudioToolkit.plan_segments(duration=1200.0, window=600) == [(0.0, 600.0), (600.0, 600.0)]


def test_long_audio_splits_and_keeps_the_remainder():
    assert AudioToolkit.plan_segments(duration=1500.0, window=600) == [
        (0.0, 600.0),
        (600.0, 600.0),
        (1200.0, 300.0),
    ]


def test_zero_duration_yields_nothing_to_transcribe():
    assert AudioToolkit.plan_segments(duration=0.0, window=600) == []


def test_window_must_be_positive():
    with pytest.raises(ValueError):
        AudioToolkit.plan_segments(duration=10.0, window=0)


class FakeProcess:
    """Mimetiza o pedaço de `asyncio.subprocess.Process` usado por `_run`."""

    def __init__(self, returncode=0, stdout=b"", stderr=b"", hang=False):
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr
        self._hang = hang
        self.killed = False

    async def communicate(self):
        if self._hang:
            await asyncio.Event().wait()  # nunca retorna — timeout precisa cortar
        return self._stdout, self._stderr

    def kill(self):
        self.killed = True

    async def wait(self):
        return self.returncode


def _patch_subprocess(monkeypatch, process: FakeProcess) -> None:
    async def fake_create_subprocess_exec(*args, **kwargs):
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)


@pytest.mark.asyncio
async def test_stderr_tail_redacts_signed_media_urls(monkeypatch):
    stderr = b"error opening https://cdn.example/x.m3u8?token=abc: not found"
    _patch_subprocess(monkeypatch, FakeProcess(returncode=1, stderr=stderr))

    with pytest.raises(AudioProcessingError) as exc:
        await AudioToolkit._run("ffmpeg", "-i", "https://cdn.example/x.m3u8?token=abc")

    message = str(exc.value)
    assert "<media-url>" in message
    assert "token=abc" not in message


@pytest.mark.asyncio
async def test_subprocess_timeout_kills_the_process_and_raises(monkeypatch):
    monkeypatch.setattr(settings, "MENTOR_SUBPROCESS_TIMEOUT_SECONDS", 0.05)
    process = FakeProcess(hang=True)
    _patch_subprocess(monkeypatch, process)

    with pytest.raises(AudioProcessingError):
        await AudioToolkit._run("ffmpeg", "-i", "x")

    assert process.killed is True


@pytest.mark.asyncio
async def test_probe_duration_rejects_non_numeric_ffprobe_output(monkeypatch):
    async def fake_run(*args):
        return "N/A\n"

    monkeypatch.setattr(AudioToolkit, "_run", staticmethod(fake_run))

    with pytest.raises(AudioProcessingError) as exc:
        await AudioToolkit.probe_duration(Path("/tmp/x.mp3"))

    assert "N/A" in str(exc.value)


@pytest.mark.asyncio
async def test_extract_audio_rejects_a_non_http_source_url():
    with pytest.raises(AudioProcessingError):
        await AudioToolkit.extract_audio("-evil-flag", Path("/tmp/out.mp3"))
