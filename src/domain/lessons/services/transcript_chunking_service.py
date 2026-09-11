"""TranscriptChunkingService — segmentos de fala em chunks com janela de tempo.

Puro, sem I/O. Por que não reusar o `ChunkingService` de `documents`: ele corta
por heading markdown e, na ausência deles, cai em janela de caractere — o que
descarta a informação que aqui é a mais valiosa, o instante em que cada frase
foi dita (spec §4).

Estratégia: empacotar segmentos consecutivos enquanto couberem em `size`; o
`start` do chunk é o do primeiro segmento e o `end` é o do último. Segmento
maior que `size` vira um chunk sozinho, sem corte: quebrá-lo no meio perderia a
única âncora temporal que ele tem, e um segmento de fala já é curto por
natureza.
"""

from src.domain.lessons.entities.transcript_segment import TranscriptSegment
from src.support.core.settings import settings

Chunk = tuple[str, float, float]


class TranscriptChunkingService:
    def __init__(self, size: int | None = None) -> None:
        self.size = size if size is not None else settings.MENTOR_CHUNK_SIZE
        if self.size <= 0:
            raise ValueError("size deve ser positivo")

    def split(self, segments: list[TranscriptSegment]) -> list[Chunk]:
        usable = [s for s in segments if s.text.strip()]
        if not usable:
            return []

        chunks: list[Chunk] = []
        texts: list[str] = []
        start = 0.0
        end = 0.0

        for segment in usable:
            text = segment.text.strip()
            if not texts:
                texts, start, end = [text], segment.start, segment.end
                continue
            candidate = len(" ".join(texts)) + 1 + len(text)
            if candidate > self.size:
                # Allow exceeding size by a small margin (10%) to avoid fragmenting small segments
                if candidate <= self.size * 1.1:
                    texts.append(text)
                    end = segment.end
                else:
                    chunks.append((" ".join(texts), start, end))
                    texts, start, end = [text], segment.start, segment.end
            else:
                texts.append(text)
                end = segment.end

        chunks.append((" ".join(texts), start, end))
        return chunks
