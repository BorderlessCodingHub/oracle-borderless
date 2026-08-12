from contextlib import nullcontext
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from src.domain.documents.actions.sync_knowledge_base_action import SyncKnowledgeBaseAction
from src.domain.documents.entities.document import Document
from src.support.clients.notion.notion_client import NotionPage
from src.support.core.settings import settings


def _dt(day: int) -> datetime:
    return datetime(2026, 7, day, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _roots(monkeypatch):
    monkeypatch.setattr(settings, "NOTION_KB_ROOT_PAGE_IDS", "rootA,rootB", raising=False)


def _approved(
    page_id: str,
    edited: datetime,
    section: str | None = None,
    kb_root_page_id: str = "roota",
) -> NotionPage:
    return NotionPage(
        id=page_id, title=f"Doc {page_id}", content="", url="https://n", is_approved=True,
        last_edited_time=edited, section=section, kb_root_page_id=kb_root_page_id,
    )


def _existing(
    page_id: str,
    edited: datetime | None,
    deleted: bool = False,
    kb_root_page_id: str = "roota",
) -> Document:
    """Documento já com provenência correta (mesmo root de `_approved`) por
    padrão — os testes que não são sobre provenância não devem disparar
    reingest por causa dela."""
    now = _dt(1)
    return Document(
        uuid=uuid4(), notion_page_id=page_id, title=f"Doc {page_id}", content="c",
        source_url="https://n", status="approved", created_at=now, updated_at=now,
        deleted_at=_dt(1) if deleted else None, last_edited_time=edited,
        kb_root_page_id=kb_root_page_id,
    )


class FakeNotion:
    def __init__(self, approved: list[NotionPage]):
        self._approved = approved

    async def list_approved_pages(self) -> list[NotionPage]:
        return self._approved

    async def get_page(self, page_id: str) -> NotionPage:
        page = next(p for p in self._approved if p.id == page_id)
        return NotionPage(page.id, page.title, "conteúdo completo", page.url, True, page.last_edited_time)


class FakeIngest:
    def __init__(self, fail_on: set[str] | None = None):
        self.executed: list[str] = []
        self.documents: list[Document] = []
        self.fail_on = fail_on or set()

    async def execute(self, document: Document) -> Document:
        if document.notion_page_id in self.fail_on:
            raise RuntimeError(f"boom {document.notion_page_id}")
        self.executed.append(document.notion_page_id)
        self.documents.append(document)
        return document


class FakeDocRepo:
    def __init__(self, existing: list[Document]):
        self._existing = existing
        self.soft_deleted: list[str] = []

    async def list_all(self) -> list[Document]:
        return list(self._existing)

    async def soft_delete_by_page_id(self, page_id: str, when: datetime) -> None:
        self.soft_deleted.append(page_id)


class FakeChunkRepo:
    def __init__(self):
        self.cleared: list = []

    async def replace_for_document(self, document_id, chunks) -> None:
        self.cleared.append(document_id)


def _action(notion, ingest, docs, chunks) -> SyncKnowledgeBaseAction:
    # atomic=nullcontext: em unit test não há sessão/savepoint real.
    return SyncKnowledgeBaseAction(
        notion=notion, ingest=ingest, documents=docs, chunks=chunks, atomic=nullcontext
    )


@pytest.mark.asyncio
async def test_new_page_is_ingested():
    notion = FakeNotion([_approved("a", _dt(5))])
    ingest = FakeIngest()
    action = _action(notion, ingest, FakeDocRepo([]), FakeChunkRepo())
    report = await action.execute()
    assert ingest.executed == ["a"]
    assert report.ingested == 1 and report.total_approved == 1


@pytest.mark.asyncio
async def test_unchanged_page_is_skipped():
    notion = FakeNotion([_approved("a", _dt(5))])
    ingest = FakeIngest()
    action = _action(notion, ingest, FakeDocRepo([_existing("a", _dt(5))]), FakeChunkRepo())
    report = await action.execute()
    assert ingest.executed == []
    assert report.skipped == 1 and report.ingested == 0


@pytest.mark.asyncio
async def test_edited_page_is_reingested():
    notion = FakeNotion([_approved("a", _dt(9))])  # mais novo
    ingest = FakeIngest()
    action = _action(notion, ingest, FakeDocRepo([_existing("a", _dt(5))]), FakeChunkRepo())
    report = await action.execute()
    assert ingest.executed == ["a"] and report.ingested == 1


@pytest.mark.asyncio
async def test_page_out_of_scope_is_removed():
    notion = FakeNotion([_approved("a", _dt(5))])  # 'b' não está mais aprovado
    ingest = FakeIngest()
    stale = _existing("b", _dt(5))
    docs = FakeDocRepo([_existing("a", _dt(5)), stale])
    chunks = FakeChunkRepo()
    report = await _action(notion, ingest, docs, chunks).execute()
    assert docs.soft_deleted == ["b"]
    assert stale.uuid in chunks.cleared
    assert report.removed == 1


@pytest.mark.asyncio
async def test_already_deleted_page_not_removed_again():
    notion = FakeNotion([_approved("a", _dt(5))])
    docs = FakeDocRepo([_existing("a", _dt(5)), _existing("b", _dt(5), deleted=True)])
    chunks = FakeChunkRepo()
    report = await _action(notion, FakeIngest(), docs, chunks).execute()
    assert docs.soft_deleted == [] and report.removed == 0


@pytest.mark.asyncio
async def test_limit_bounds_ingestion_and_skips_removal():
    notion = FakeNotion([_approved("a", _dt(5)), _approved("b", _dt(5)), _approved("c", _dt(5))])
    ingest = FakeIngest()
    # 'z' está no banco e fora do aprovado — NÃO deve ser removido num run limitado.
    docs = FakeDocRepo([_existing("z", _dt(5))])
    report = await _action(notion, ingest, docs, FakeChunkRepo()).execute(limit=2)
    assert len(ingest.executed) == 2
    assert docs.soft_deleted == [] and report.removed == 0


@pytest.mark.asyncio
async def test_limit_advances_past_already_ingested_pages():
    """Blocos repetidos devem AVANÇAR: --limit conta ingestões novas, pula as já feitas."""
    notion = FakeNotion([
        _approved("a", _dt(5)), _approved("b", _dt(5)),
        _approved("c", _dt(5)), _approved("d", _dt(5)),
    ])
    ingest = FakeIngest()
    # a, b já ingeridos e inalterados → devem ser pulados; limit 2 deve pegar c, d.
    docs = FakeDocRepo([_existing("a", _dt(5)), _existing("b", _dt(5))])
    report = await _action(notion, ingest, docs, FakeChunkRepo()).execute(limit=2)
    assert ingest.executed == ["c", "d"]
    assert report.ingested == 2 and report.skipped == 2


@pytest.mark.asyncio
async def test_failing_page_is_counted_and_does_not_stop_others():
    notion = FakeNotion([_approved("a", _dt(5)), _approved("bad", _dt(5)), _approved("c", _dt(5))])
    ingest = FakeIngest(fail_on={"bad"})
    report = await _action(notion, ingest, FakeDocRepo([]), FakeChunkRepo()).execute()
    assert ingest.executed == ["a", "c"]  # 'bad' pulada, loop seguiu
    assert report.ingested == 2 and report.failed == 1


@pytest.mark.asyncio
async def test_force_reingests_even_when_unchanged():
    notion = FakeNotion([_approved("a", _dt(5))])
    ingest = FakeIngest()
    action = _action(notion, ingest, FakeDocRepo([_existing("a", _dt(5))]), FakeChunkRepo())
    report = await action.execute(force=True)
    assert ingest.executed == ["a"] and report.ingested == 1


@pytest.mark.asyncio
async def test_stale_provenance_root_triggers_reingest_without_force():
    """Documento existente, NÃO stale (mesmo last_edited_time), mas com
    `kb_root_page_id` divergente do root sob o qual a página foi descoberta agora
    (ex.: `NULL` pré-migração 0004) precisa ser reingerido mesmo sem `--force` —
    senão a base fica presa com provenência velha para sempre após uma migração
    ou troca de root.

    Também trava a regressão em que a reconciliação (que roda no mesmo
    `execute()`, já que este não é um run parcial) desfazia a auto-cura:
    lendo a procedência do snapshot velho de `existing` em vez do root
    recém-descoberto, ela via `kb_root_page_id=None` e soft-deletava a página
    que acabara de ser corrigida."""
    notion = FakeNotion([_approved("a", _dt(5))])
    ingest = FakeIngest()
    stale_doc = _existing("a", _dt(5))  # last_edited_time igual — não é stale por timestamp
    stale_doc.kb_root_page_id = None  # provenência pré-migração 0004
    docs = FakeDocRepo([stale_doc])
    action = _action(notion, ingest, docs, FakeChunkRepo())

    report = await action.execute()  # sem force

    assert ingest.executed == ["a"]
    assert report.ingested == 1 and report.skipped == 0
    assert report.removed == 0
    assert docs.soft_deleted == []


@pytest.mark.asyncio
async def test_provenance_is_stamped_from_traversal_section():
    """`get_page` (FakeNotion) devolve uma NotionPage 'fresca' sem `section` — como
    o client real. A `section` só existe na `page` da travessia (`list_approved_pages`).
    Sem `full.section = page.section` no sync, a provenência se perderia."""
    notion = FakeNotion([
        _approved(
            "a", _dt(5), section="Bootcamps",
            kb_root_page_id="23d8d655-c889-806d-8828-d527ce6a1529",
        )
    ])
    ingest = FakeIngest()
    action = _action(notion, ingest, FakeDocRepo([]), FakeChunkRepo())

    await action.execute()

    assert len(ingest.documents) == 1
    doc = ingest.documents[0]
    assert doc.kb_section == "Bootcamps"
    assert doc.kb_root_page_id == "23d8d655c889806d8828d527ce6a1529"  # sem hífens


@pytest.mark.asyncio
async def test_ingests_each_page_under_its_own_root():
    notion = FakeNotion([
        _approved("a", _dt(5), kb_root_page_id="roota"),
        _approved("b", _dt(5), kb_root_page_id="rootb"),
    ])
    ingest = FakeIngest()

    await _action(notion, ingest, FakeDocRepo([]), FakeChunkRepo()).execute()

    # FakeNotion.get_page devolve um NotionPage novo, sem procedência — é
    # exatamente por isso que a action precisa copiar o root da página
    # descoberta para a página completa antes de mapear.
    assert {d.notion_page_id: d.kb_root_page_id for d in ingest.documents} == {
        "a": "roota",
        "b": "rootb",
    }


@pytest.mark.asyncio
async def test_soft_deletes_documents_whose_root_left_the_allowlist():
    # A página nem aparece mais na descoberta, e sua procedência é de um root
    # que saiu da allowlist — os dois motivos de saída de escopo.
    docs = FakeDocRepo([_existing("z", _dt(5), kb_root_page_id="rootremovido")])
    chunks = FakeChunkRepo()

    report = await _action(FakeNotion([]), FakeIngest(), docs, chunks).execute()

    assert report.removed == 1
    assert docs.soft_deleted == ["z"]
    assert chunks.cleared != []


@pytest.mark.asyncio
async def test_soft_deletes_a_still_approved_page_whose_root_was_dropped():
    # Caso que a lista de aprovados NÃO revela: a página continua sendo
    # descoberta, mas sob um root fora da allowlist vigente.
    notion = FakeNotion([_approved("y", _dt(5), kb_root_page_id="rootfora")])
    docs = FakeDocRepo([_existing("y", _dt(5), kb_root_page_id="rootfora")])

    report = await _action(notion, FakeIngest(), docs, FakeChunkRepo()).execute()

    assert docs.soft_deleted == ["y"]
    assert report.removed == 1
