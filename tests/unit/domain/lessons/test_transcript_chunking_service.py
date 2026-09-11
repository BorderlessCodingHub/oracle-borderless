import pytest

from src.domain.lessons.entities.transcript_segment import TranscriptSegment
from src.domain.lessons.services.transcript_chunking_service import TranscriptChunkingService


def seg(text: str, start: float, end: float) -> TranscriptSegment:
    return TranscriptSegment(text=text, start=start, end=end)


def test_empty_input_yields_no_chunks():
    assert TranscriptChunkingService(size=100).split([]) == []


def test_segments_under_the_limit_become_a_single_chunk():
    chunks = TranscriptChunkingService(size=100).split(
        [seg("olá pessoal", 0.0, 2.0), seg("hoje é sobre tokens", 2.0, 5.0)]
    )
    assert chunks == [("olá pessoal hoje é sobre tokens", 0.0, 5.0)]


def test_packing_fills_exactly_to_the_limit_then_breaks():
    # 15 + 1 (espaço) + 4 = 20 == size: cabe (limite inclusivo); o próximo estoura.
    service = TranscriptChunkingService(size=20)
    chunks = service.split(
        [seg("a" * 15, 0.0, 1.0), seg("b" * 4, 1.0, 2.0), seg("c" * 10, 2.0, 3.0)]
    )
    assert [c[0] for c in chunks] == ["a" * 15 + " " + "b" * 4, "c" * 10]
    assert chunks[0][1] == 0.0 and chunks[0][2] == 2.0
    assert chunks[1][1] == 2.0 and chunks[1][2] == 3.0


def test_one_char_over_the_limit_breaks_the_chunk():
    # 15 + 1 + 5 = 21 > 20: NÃO cabe. "Até size" é teto duro, sem tolerância.
    service = TranscriptChunkingService(size=20)
    chunks = service.split([seg("a" * 15, 0.0, 1.0), seg("b" * 5, 1.0, 2.0)])
    assert [c[0] for c in chunks] == ["a" * 15, "b" * 5]


def test_a_segment_longer_than_the_limit_becomes_its_own_chunk_unsplit():
    # Cortar dentro de um segmento perderia a única âncora temporal que ele tem.
    long_text = "x" * 50
    chunks = TranscriptChunkingService(size=20).split([seg(long_text, 10.0, 40.0)])
    assert chunks == [(long_text, 10.0, 40.0)]


def test_blank_segments_are_dropped_without_breaking_the_window():
    chunks = TranscriptChunkingService(size=100).split(
        [seg("  ", 0.0, 1.0), seg("conteúdo", 1.0, 2.0), seg("", 2.0, 3.0)]
    )
    assert chunks == [("conteúdo", 1.0, 2.0)]


def test_chunks_come_back_in_chronological_order():
    service = TranscriptChunkingService(size=10)
    chunks = service.split([seg("aaaaaaa", 0.0, 1.0), seg("bbbbbbb", 1.0, 2.0), seg("ccccccc", 2.0, 3.0)])
    starts = [c[1] for c in chunks]
    assert starts == sorted(starts)


def test_size_must_be_positive():
    with pytest.raises(ValueError):
        TranscriptChunkingService(size=0)
