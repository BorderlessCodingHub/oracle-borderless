import type {
  AskEvent,
  AskInput,
  Citation,
  ConversationDetail,
  ConversationSummary,
} from "../types";
import { apiUrl, getJSON } from "./client";
import { parseSSE } from "./sse";

interface SummaryDTO { id: string; title: string | null; updated_at: string; }
interface MessageDTO { role: "user" | "assistant"; content: string; sources?: Citation[] | null; }
interface DetailDTO { id: string; title: string | null; messages: MessageDTO[]; }

export async function listConversations(): Promise<ConversationSummary[]> {
  const rows = await getJSON<SummaryDTO[]>("/conversations");
  return rows.map((r) => ({ id: r.id, title: r.title, updatedAt: r.updated_at }));
}

export async function getConversation(id: string): Promise<ConversationDetail> {
  const dto = await getJSON<DetailDTO>(`/conversations/${id}`);
  return {
    id: dto.id,
    title: dto.title,
    messages: dto.messages.map((m) => ({
      role: m.role,
      content: m.content,
      sources: m.sources ?? undefined,
    })),
  };
}

export async function* askStream(input: AskInput): AsyncGenerator<AskEvent> {
  const resp = await fetch(apiUrl("/conversations/ask"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question: input.question, conversation_id: input.conversationId ?? null }),
  });
  if (!resp.ok || !resp.body) {
    yield { type: "error", message: `Falha na requisição (${resp.status})` };
    return;
  }
  for await (const { event, data } of parseSSE(resp.body)) {
    const payload = safeParse(data);
    if (event === "conversation") yield { type: "conversation", id: payload.id };
    else if (event === "token") yield { type: "token", text: payload.text };
    else if (event === "sources") yield { type: "sources", citations: payload.citations ?? [] };
    else if (event === "error") yield { type: "error", message: payload.message ?? "erro" };
    else if (event === "done") yield { type: "done" };
  }
}

function safeParse(data: string): any {
  try { return JSON.parse(data); } catch { return {}; }
}
