import type {
  AskEvent,
  AskInput,
  Citation,
  ConversationDetail,
  ConversationSummary,
} from "../types";
import { apiUrl, getJSON, handleUnauthorized } from "./client";
import { buildAskBody, parseStreamEvents, toAskEvents } from "./streamEvents";

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
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify(buildAskBody(input.question, input.conversationId)),
  });
  if (resp.status === 401) {
    handleUnauthorized();
    yield { type: "error", message: "Sessão expirada — faça login de novo." };
    return;
  }
  if (!resp.ok || !resp.body) {
    yield { type: "error", message: `Falha na requisição (${resp.status})` };
    return;
  }
  yield* toAskEvents(parseStreamEvents(resp.body));
}
