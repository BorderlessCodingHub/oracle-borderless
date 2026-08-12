from dataclasses import dataclass, field

from src.support.clients.notion.notion_client import WorkspaceRootPage


@dataclass
class KbRootDrift:
    """Diferença entre a allowlist de roots e o que a integração enxerga.

    `unlisted`: liberado no Notion mas fora da allowlist — alguém liberou algo e
    o oráculo ainda não lê. `missing`: na allowlist mas invisível — permissão
    revogada, página movida, ou id errado na env var.
    """

    unlisted: list[WorkspaceRootPage] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)

    @property
    def has_drift(self) -> bool:
        return bool(self.unlisted or self.missing)
