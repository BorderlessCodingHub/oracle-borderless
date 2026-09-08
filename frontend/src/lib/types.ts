export interface Citation {
  source_type: string;
  title: string;
  url: string;
  snippet: string;
  page_id?: string | null;
}

export type MessageRole = "user" | "assistant";

export interface Message {
  role: MessageRole;
  content: string;
  sources?: Citation[];
}

export interface ConversationSummary {
  id: string;
  title: string | null;
  updatedAt: string;
}

export interface ConversationDetail {
  id: string;
  title: string | null;
  messages: Message[];
}

export interface AskInput {
  question: string;
  conversationId?: string;
}

/** Eventos internos do turno. É o que o hook consome; a tradução dos
 * StreamEvents do fio para isto fica em lib/api/streamEvents.ts (ADR-0021). */
export type AskEvent =
  | { type: "run_started"; conversationId: string }
  | { type: "step"; name: string; phase: "started" | "finished"; detail?: Record<string, unknown> }
  | { type: "tool_call_start"; id: string; name: string }
  | { type: "tool_call_args"; id: string; delta: string }
  | { type: "tool_call_end"; id: string }
  | { type: "tool_call_result"; id: string; status: "ok" | "error" }
  | { type: "token"; text: string }
  | { type: "sources"; citations: Citation[] }
  | { type: "error"; message: string }
  | { type: "done" };
