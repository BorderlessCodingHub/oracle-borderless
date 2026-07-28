"""Normalização de ids de página do Notion.

O MCP devolve UUID com hífens; ids vindos de citação, de env var ou digitados
pelo modelo podem vir sem. Comparar sempre pela forma normalizada.
"""


def normalize_page_id(value: str | None) -> str | None:
    """Id sem hífens, minúsculo e sem espaços nas pontas. `None` se vazio."""
    if value is None:
        return None
    normalized = value.replace("-", "").strip().lower()
    return normalized or None
