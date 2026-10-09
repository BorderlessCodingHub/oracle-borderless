from dataclasses import dataclass, field


@dataclass
class LessonGap:
    """Uma pergunta que a aula não cobriu — pauta de gravação (spec §9.3, backlog)."""

    lesson_id: str | None
    program_slug: str | None
    question: str
    asked_at: str
    user_email: str | None


@dataclass
class LessonEngagement:
    """Retenção de uma aula: quantos alunos distintos perguntaram e quanto o
    mentor citou. Muitos turnos com POUCAS citações é aula confusa; muitos
    turnos com MUITAS citações é aula sendo minerada de verdade."""

    lesson_id: str | None
    turns: int
    distinct_users: int
    avg_citations: float
    gap_ratio: float


@dataclass
class MentorInsights:
    """As duas leituras de produto do modo mentor, para a aba `/ops`."""

    gaps: list[LessonGap] = field(default_factory=list)
    engagement: list[LessonEngagement] = field(default_factory=list)
