import pytest

from src.support.clients.transcription.audio_toolkit import AudioToolkit


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
