"""Wrapper fino de ffmpeg/ffprobe. O planejamento de fatias é puro e separado
da execução para poder ser testado sem o binário instalado."""

import asyncio
import logging
import re
from pathlib import Path

from src.support.core.exceptions import DomainError
from src.support.core.settings import settings

logger = logging.getLogger(__name__)


class AudioProcessingError(DomainError):
    """ffmpeg/ffprobe falhou ou não está disponível."""


class AudioToolkit:
    @staticmethod
    def plan_segments(duration: float, window: int) -> list[tuple[float, float]]:
        """Janelas (início, duração) que cobrem o áudio inteiro sem sobra.

        Existe porque a API de transcrição limita o arquivo a 25 MB e uma aula
        de 1h passa disso — sem fatiar, o pipeline quebra exatamente nas aulas
        mais longas (spec §7).
        """
        if window <= 0:
            raise ValueError("window deve ser positivo")
        if duration <= 0:
            return []
        segments: list[tuple[float, float]] = []
        start = 0.0
        while start < duration:
            segments.append((start, min(float(window), duration - start)))
            start += window
        return segments

    @staticmethod
    async def _run(*args: str) -> str:
        process = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        timeout = settings.MENTOR_SUBPROCESS_TIMEOUT_SECONDS
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            # ffmpeg/ffprobe travado (mídia gigante, rede pendurada, etc.) não
            # pode prender o lote inteiro — mata o processo e segue como falha
            # da aula, não do lote.
            process.kill()
            await process.wait()
            raise AudioProcessingError(f"{args[0]} excedeu {timeout}s")
        if process.returncode != 0:
            tail = stderr.decode(errors="replace")[-400:]
            # A URL de mídia é assinada (token na query string): nunca pode
            # vazar para failure_reason nem para o log via stderr do ffmpeg.
            tail = re.sub(r"https?://\S+", "<media-url>", tail)
            raise AudioProcessingError(f"{args[0]} saiu com {process.returncode}: {tail}")
        return stdout.decode(errors="replace")

    @classmethod
    async def extract_audio(cls, source_url: str, dest: Path) -> None:
        """Mono 16 kHz: o suficiente para fala, e a menor conta possível.

        `source_url` pode ser um manifesto HLS (`.m3u8`) — o ffmpeg lê direto
        via `-i <url>`, sem precisar baixar o vídeo antes.
        """
        if not source_url.startswith(("http://", "https://")):
            # Um valor começando com `-` seria lido como opção do ffmpeg, e
            # esquemas como `file:`/`concat:` seriam honrados — a mídia do
            # catálogo é sempre uma URL http(s) assinada, nunca outra coisa.
            raise AudioProcessingError("URL de mídia inválida")
        await cls._run(
            settings.MENTOR_FFMPEG_BIN, "-y", "-i", source_url,
            "-vn", "-ac", "1", "-ar", "16000", "-b:a", "64k", str(dest),
        )

    @classmethod
    async def probe_duration(cls, path: Path) -> float:
        out = await cls._run(
            settings.MENTOR_FFPROBE_BIN, "-v", "error",
            "-show_entries", "format=duration", "-of", "csv=p=0", str(path),
        )
        text = out.strip()
        try:
            return float(text)
        except ValueError:
            # ffprobe imprime "N/A" quando não consegue determinar a duração
            # (ex.: stream sem metadado de duração) — melhor falhar cedo e
            # claramente do que deixar o `float()` explodir com um traceback
            # genérico lá na frente.
            raise AudioProcessingError(
                f"ffprobe não devolveu duração numérica: {text!r}"
            ) from None

    @classmethod
    async def slice(cls, path: Path, start: float, length: float, dest: Path) -> None:
        await cls._run(
            settings.MENTOR_FFMPEG_BIN, "-y", "-ss", str(start), "-t", str(length),
            "-i", str(path), "-c", "copy", str(dest),
        )
