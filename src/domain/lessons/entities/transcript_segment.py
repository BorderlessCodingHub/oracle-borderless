from dataclasses import dataclass


@dataclass(frozen=True)
class TranscriptSegment:
    """Um segmento cru do speech-to-text, antes de virar chunk."""

    text: str
    start: float
    end: float

    def shifted(self, offset: float) -> "TranscriptSegment":
        """Desloca no tempo — usado ao concatenar blocos de áudio fatiados."""
        return TranscriptSegment(text=self.text, start=self.start + offset, end=self.end + offset)
