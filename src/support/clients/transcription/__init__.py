"""Client de áudio e transcrição (ffmpeg/ffprobe + OpenAI whisper-1)."""

from src.support.clients.transcription.audio_toolkit import AudioProcessingError, AudioToolkit
from src.support.clients.transcription.transcription_client import TranscriptionClient

__all__ = ["AudioProcessingError", "AudioToolkit", "TranscriptionClient"]
