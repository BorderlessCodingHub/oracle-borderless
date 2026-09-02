import type { Citation, ConversationDetail, ConversationSummary } from "../types";

const META_CITATIONS: Citation[] = [
  {
    source_type: "notion",
    title: "SOP-GM-06 — Nomenclatura de Campanhas e Conjuntos de Anúncios",
    url: "https://www.notion.so/sop-gm-06",
    snippet: "Campanha: [🔥/❄] [Tipo] - [Funil]…",
    page_id: "sop-gm-06",
  },
  {
    source_type: "notion",
    title: "SOP-GM-04 — UTM Convention & Rastreamento de Tráfego",
    url: "https://www.notion.so/sop-gm-04",
    snippet: "Padrão de UTMs por campanha e origem…",
    page_id: "sop-gm-04",
  },
  {
    source_type: "web",
    title: "Meta Ads — nomenclatura recomendada",
    url: "https://www.facebook.com/business/help",
    snippet: "Convenções recomendadas para nomear campanhas e conjuntos.",
    page_id: null,
  },
];

export const DEMO_CONVERSATIONS: ConversationSummary[] = [
  { id: "c1", title: "Nomenclatura de campanhas no Meta Ads", updatedAt: "2026-07-20T10:00:00Z" },
  { id: "c2", title: "Como funciona a Review Mensal (1:1)?", updatedAt: "2026-07-19T10:00:00Z" },
  { id: "c3", title: "Processo de upload no YouTube", updatedAt: "2026-07-18T10:00:00Z" },
  { id: "c4", title: "Detalhes da vaga de Lead Engineer", updatedAt: "2026-07-12T10:00:00Z" },
];

export const DEMO_DETAILS: Record<string, ConversationDetail> = {
  c1: {
    id: "c1",
    title: "Nomenclatura de campanhas no Meta Ads",
    messages: [
      { role: "user", content: "Qual é a nomenclatura oficial de campanhas no Meta Ads?" },
      {
        role: "assistant",
        content:
          "A nomenclatura oficial está no SOP-GM-06 e usa uma estrutura de três níveis:\n\n" +
          "1. Campanha — [🔥 ou ❄] [Tipo] - [Funil]. O símbolo de temperatura (quente/frio) é obrigatório.\n" +
          "2. Conjunto de anúncios — [Verba Diária] - [Público] - [Nome/Tema], com a verba sempre no formato R$ XX/dia e atualizada sempre que mudar.\n" +
          "3. Anúncio — [Nome do Editor] - [Nome do Anúncio].\n\n" +
          "O owner operacional é o Nathan (Tráfego Pago) e o GOM aprova. Quer que eu detalhe os erros comuns listados no SOP?",
        sources: META_CITATIONS,
      },
    ],
  },
};

export const DEMO_ANSWER =
  "A nomenclatura oficial está no **SOP-GM-06** e segue três níveis:\n\n" +
  "1. **Campanha** — `[🔥/❄] [Tipo] - [Funil]`\n" +
  "2. **Conjunto de anúncios** — `[Verba] - [Público] - [Tema]`\n" +
  "3. **Anúncio** — `[Editor] - [Nome]`\n\n" +
  "O símbolo de temperatura (quente/frio) é **obrigatório** na campanha.";

export const DEMO_ANSWER_CITATIONS = META_CITATIONS;
