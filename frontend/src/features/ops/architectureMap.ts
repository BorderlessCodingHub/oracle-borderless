/**
 * REGISTRO ÚNICO das caixas do mapa de arquitetura.
 *
 * ⚠️ REGRA DO MAPA HONESTO: mudou o pipeline (arquivo renomeado, etapa nova,
 * etapa removida), muda este registro NO MESMO COMMIT. `architectureMap.test.ts`
 * falha se qualquer caminho declarado aqui deixar de existir — é o que impede o
 * desenho de envelhecer em silêncio. Ver a spec de 2026-08-03, "Requisito: o
 * mapa não pode mentir".
 *
 * `metric` é a chave lida do payload de /ops/overview para a caixa exibir número.
 */

export interface MapBox {
  id: string;
  label: string;
  description: string;
  files: string[];
  metric?: string;
}

export interface MapBand {
  id: string;
  title: string;
  boxes: MapBox[];
}

export const ARCHITECTURE_MAP: MapBand[] = [
  {
    id: "ingestion",
    title: "Ingestão — base de conhecimento",
    boxes: [
      {
        id: "notion-mcp",
        label: "Notion MCP",
        description: "Lê o subtree de cada root liberado via MCP. Fora dos roots, nada é visitado.",
        files: ["src/support/clients/notion/notion_client.py", "src/support/clients/notion/mcp_session.py"],
      },
      {
        id: "curation",
        label: "Curadoria",
        description: "Rejeita linha de banco e títulos na denylist. Segunda linha de defesa do escopo.",
        files: ["src/domain/documents/services/knowledge_curation_policy.py"],
      },
      {
        id: "sync",
        label: "Sync",
        description: "Full e incremental, idempotente. Reconcilia o que saiu do escopo.",
        files: [
          "src/domain/documents/actions/sync_knowledge_base_action.py",
          "src/app/console/jobs/sync_knowledge_base_job.py",
        ],
        metric: "sync",
      },
      {
        id: "chunking",
        label: "Limpeza + chunking",
        description: "Remove markup do Notion e quebra por heading.",
        files: [
          "src/domain/documents/services/notion_markup_cleaner.py",
          "src/domain/documents/services/chunking_service.py",
        ],
      },
      {
        id: "embeddings",
        label: "Embeddings",
        description: "text-embedding-3-small, 1536 dimensões.",
        files: ["src/support/clients/embeddings/embeddings_client.py"],
      },
      {
        id: "store",
        label: "documents · chunks",
        description: "Postgres + pgvector, índice HNSW cosseno.",
        files: [
          "src/domain/documents/models/document.py",
          "src/domain/documents/models/document_chunk.py",
        ],
        metric: "knowledge",
      },
    ],
  },
  {
    id: "turn",
    title: "Turno — da pergunta à resposta",
    boxes: [
      {
        id: "ask",
        label: "Pergunta",
        description: "POST /conversations/ask, resposta em SSE.",
        files: ["src/app/api/controllers/conversation_controller.py"],
      },
      {
        id: "recency",
        label: "Recência",
        description: "Histórico por orçamento de tokens, não por número de turnos.",
        files: ["src/domain/conversations/repositories/message_repository.py"],
        metric: "recency",
      },
      {
        id: "gate",
        label: "Retrieval gate",
        description: "Modelo pequeno decide buscar ou não, e reescreve a query. Fail-open.",
        files: ["src/support/agent/retrieval_gate.py"],
        metric: "gate",
      },
      {
        id: "retrieval",
        label: "Retrieval + limiar",
        description: "Top-k no pgvector, escopado aos roots, cortado pela distância máxima.",
        files: [
          "src/domain/documents/actions/search_knowledge_base_action.py",
          "src/domain/documents/repositories/document_chunk_repository.py",
        ],
        metric: "retrieval",
      },
      {
        id: "refusal",
        label: "Recusa padrão",
        description: "Nada passou do limiar: resposta determinística, sem chamar o LLM.",
        files: ["src/domain/conversations/services/out_of_scope_reply.py"],
        metric: "refusals",
      },
      {
        id: "engine",
        label: "OracleEngine + tools",
        description: "Pydantic AI. Grounding, citação e recusa vêm do system prompt.",
        files: [
          "src/support/agent/oracle_engine.py",
          "src/support/agent/tools.py",
          "src/support/agent/prompts.py",
        ],
        metric: "engine",
      },
      {
        id: "persist",
        label: "Persistência + trace",
        description: "Resposta e trace gravados pós-stream, em sessão própria.",
        files: [
          "src/domain/conversations/actions/append_assistant_message_action.py",
          "src/domain/observability/actions/record_turn_trace_action.py",
        ],
        metric: "turns",
      },
    ],
  },
];
