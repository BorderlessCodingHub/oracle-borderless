from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class CitationResponse(BaseModel):
    source_type: str
    title: str
    url: str
    snippet: str
    page_id: str | None = None


class MessageResponse(BaseModel):
    role: str
    content: str
    sources: list[CitationResponse] | None = None
    navigation: dict | None = None

    @classmethod
    def from_entity(cls, m) -> "MessageResponse":
        sources = (
            [
                CitationResponse(
                    source_type=c.source_type,
                    title=c.title,
                    url=c.url,
                    snippet=c.snippet,
                    page_id=c.page_id,
                )
                for c in m.sources
            ]
            if m.sources
            else None
        )
        return cls(role=m.role, content=m.content, sources=sources, navigation=m.navigation)


class ConversationSummaryResponse(BaseModel):
    id: UUID
    title: str | None
    updated_at: datetime
    mode: str | None = None

    @classmethod
    def from_entity(cls, c) -> "ConversationSummaryResponse":
        return cls(id=c.uuid, title=c.title, updated_at=c.updated_at, mode=c.mode)


class ConversationDetailResponse(BaseModel):
    id: UUID
    title: str | None
    messages: list[MessageResponse]

    @classmethod
    def from_entity(cls, c, messages) -> "ConversationDetailResponse":
        return cls(
            id=c.uuid,
            title=c.title,
            messages=[MessageResponse.from_entity(m) for m in messages],
        )
