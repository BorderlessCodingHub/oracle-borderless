"""Mede a distância do melhor chunk para um conjunto fixo de perguntas.

Serve para reconferir `RAG_MAX_DISTANCE` quando a base muda de tamanho: a
calibração de 2026-07-28 valia para 42 documentos.
"""

from sqlalchemy import select

from src.domain.documents.models.document import DocumentModel
from src.domain.documents.models.document_chunk import DocumentChunkModel
from src.support.clients.embeddings.embeddings_client import get_embeddings_client
from src.support.core.console.command import Command
from src.support.core.context import CurrentAsyncSessionContext
from src.support.core.database import AsyncSessionLocal
from src.support.core.settings import settings

DENTRO = [
    "o que é o Web3 Bootcamp?",
    "quais programas existem no ecossistema?",
    "o que é o PSP?",
    "como funciona a mentoria BASE?",
    "quais são as entregáveis da mentoria PSP?",
    "o que é o BASE Gate?",
    "quando é a edição #02 do bootcamp?",
]
FORA = [
    "qual é o processo de renovação do PSP?",
    "como funciona o onboarding de novo mentorado?",
    "o que diz o SOP-GM-01 sobre transferência de ativos?",
    "qual a convenção de UTM para campanhas?",
    "como criar eventos no Discord?",
    "qual a capital da Austrália?",
    "como faço um bolo de cenoura?",
    "quem ganhou a copa de 2022?",
    "qual o melhor framework de frontend?",
]


def format_row(distance: float, question: str, title: str, threshold: float) -> str:
    veredito = "PASSA " if distance <= threshold else "RECUSA"
    return f"{veredito} {distance:.3f}  {question[:52]:<52} -> {title[:38]}"


class KnowledgeCalibrateCommand(Command):
    signature = "knowledge:calibrate"
    description = (
        "Mede a distância do melhor chunk para perguntas dentro e fora do escopo. "
        "Use para reconferir RAG_MAX_DISTANCE quando a base mudar de tamanho."
    )

    async def handle(self) -> None:
        limiar = settings.RAG_MAX_DISTANCE
        if not settings.kb_root_page_ids:
            print("NOTION_KB_ROOT_PAGE_IDS não configurado — nada a calibrar.")
            return
        embeddings = get_embeddings_client()
        print(f"RAG_MAX_DISTANCE atual: {limiar}\n")

        async with AsyncSessionLocal() as session:
            CurrentAsyncSessionContext.set(session)
            try:
                for rotulo, perguntas in (("DENTRO", DENTRO), ("FORA", FORA)):
                    print(f"===== {rotulo} DO ESCOPO =====")
                    for pergunta in perguntas:
                        vetor = await embeddings.embed_query(pergunta)
                        distancia = DocumentChunkModel.embedding.cosine_distance(vetor)
                        stmt = (
                            select(distancia.label("d"), DocumentModel.title)
                            .join(
                                DocumentModel,
                                DocumentChunkModel.document_id == DocumentModel.uuid,
                            )
                            .where(
                                DocumentModel.status == "approved",
                                DocumentModel.deleted_at.is_(None),
                                DocumentModel.kb_root_page_id.in_(settings.kb_root_page_ids),
                            )
                            .order_by(distancia)
                            .limit(1)
                        )
                        linha = (await session.execute(stmt)).first()
                        if linha is None:
                            print(f"       ----  {pergunta[:52]:<52} -> (base vazia)")
                            continue
                        print(format_row(linha.d, pergunta, linha.title, limiar))
                    print()
            finally:
                CurrentAsyncSessionContext.clear()
