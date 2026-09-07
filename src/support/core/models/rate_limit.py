from sqlalchemy import BigInteger, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from src.support.core.models.base_model import BaseModel


class RateLimitModel(BaseModel):
    """Contador de janela fixa para rate limit (ADR-0017).

    Em memória não funciona: multi-worker/serverless fragmenta e reseta o
    contador. Uma linha por chave; `window_start` é o nº do bucket
    (epoch_ms // window_ms).
    """

    __tablename__ = "rate_limits"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    window_start: Mapped[int] = mapped_column(BigInteger, nullable=False)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
