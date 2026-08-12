"""Configuração central da aplicação, lida do ambiente (.env) via pydantic-settings."""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

from src.support.utils.notion_ids import normalize_page_id


class Settings(BaseSettings):
    """Todas as variáveis de ambiente do Oracle Borderless."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Ambiente ---
    ENVIRONMENT: Literal["development", "staging", "production"] = "development"
    DEBUG: bool = True
    ENABLE_SCHEDULER: bool = True

    # --- Aplicação ---
    APP_NAME: str = "Oracle Borderless"
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000

    # --- Banco de dados ---
    DB_HOST: str = "localhost"
    DB_PORT: int = 5432
    DB_USER: str = "oracle"
    DB_PASSWORD: str = "oracle"
    DB_NAME: str = "oracle_borderless"
    DB_NAME_TEST: str = "oracle_borderless_test"
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 3600

    # --- Base de conhecimento: Notion via MCP ---
    NOTION_MCP_URL: str | None = None
    NOTION_MCP_TOKEN: str | None = None
    # Raízes da KB: a base é EXCLUSIVAMENTE a união dos subtrees destes roots do
    # Notion, separados por vírgula. Eles são irmãos no nível do workspace — não
    # existe ancestral comum. Sem nenhum root, o sync aborta (ver NotionClient).
    NOTION_KB_ROOT_PAGE_IDS: str | None = None

    # --- LLM do oráculo (Claude ou GPT, selecionável) ---
    LLM_PROVIDER: Literal["anthropic", "openai"] = "anthropic"
    ANTHROPIC_API_KEY: str | None = None
    ANTHROPIC_MODEL: str = "claude-opus-4-8"
    OPENAI_API_KEY: str | None = None
    OPENAI_MODEL: str = "gpt-4o"
    ANTHROPIC_SMALL_MODEL: str = "claude-haiku-4-5-20251001"
    OPENAI_SMALL_MODEL: str = "gpt-4o-mini"
    GATE_TIMEOUT_SECONDS: float = 5.0
    # Juiz do eval: sempre OpenAI, independente de LLM_PROVIDER. A chave da OpenAI
    # já é obrigatória (embeddings, ADR-0008) e juiz de outra família reduz viés de
    # auto-preferência, já que as respostas avaliadas vêm do Claude.
    JUDGE_MODEL: str = "gpt-4.1-mini"
    # Onde o harness de eval grava seus reports (lidos pela página de ops)
    EVAL_REPORTS_DIR: str = "evals/reports"

    # --- Embeddings (desacoplado do provedor de chat; ver ADR-0008) ---
    EMBEDDING_PROVIDER: Literal["openai"] = "openai"
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    EMBEDDING_DIM: int = 1536

    # --- Web search (Tavily) ---
    TAVILY_API_KEY: str | None = None

    # --- RAG ---
    RAG_TOP_K: int = 6
    # Distância cosseno máxima para um chunk virar contexto. Calibrado em
    # 2026-07-28: pergunta legítima ficou <= 0.532, pergunta sem relação >= 0.615.
    RAG_MAX_DISTANCE: float = 0.55
    RAG_CHUNK_SIZE: int = 1500
    RAG_CHUNK_OVERLAP: int = 200

    # Memória episódica (M2) — recência carregada na working memory
    MEMORY_RECENCY_TOKEN_BUDGET: int = 2000
    MEMORY_RECENCY_MAX_MESSAGES: int = 50

    @property
    def database_url_async(self) -> str:
        """URL do engine assíncrono (asyncpg)."""
        return (
            f"postgresql+asyncpg://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        )

    @property
    def database_url_sync(self) -> str:
        """URL do engine síncrono (psycopg) — usado pelo jobstore do APScheduler."""
        return (
            f"postgresql+psycopg://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        )

    @property
    def database_url_async_test(self) -> str:
        """URL async do banco de testes (usado pela suíte de integração)."""
        return (
            f"postgresql+asyncpg://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME_TEST}"
        )

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    @property
    def kb_root_page_ids(self) -> tuple[str, ...]:
        """Roots da KB normalizados, deduplicados, na ordem de declaração.

        Tupla vazia significa "sem escopo configurado" — os chamadores tratam
        isso como fail-closed (aborta na descoberta, devolve vazio na leitura),
        nunca como "sem filtro". Entrada iniciada por `#` é entrada comentada.
        """
        ids: list[str] = []
        for part in (self.NOTION_KB_ROOT_PAGE_IDS or "").split(","):
            if part.lstrip().startswith("#"):
                continue
            normalized = normalize_page_id(part)
            if normalized and normalized not in ids:
                ids.append(normalized)
        return tuple(ids)


@lru_cache
def get_settings() -> Settings:
    """Instância única (cacheada) das settings."""
    return Settings()


settings = get_settings()
