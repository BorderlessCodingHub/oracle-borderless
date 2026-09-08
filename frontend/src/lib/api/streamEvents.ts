/** StreamEvents do `astream_events` no fio (ADR-0021): tipo, parser tolerante,
 * body do request e a tradução para o `AskEvent` interno. O hook e a UI não
 * conhecem o fio — só este módulo. */
import type { AskEvent, Citation } from "../types";
import { parseSSE } from "./sse";

export interface StreamEvent {
  event: string;
  name: string;
  run_id: string;
  tags: string[];
  metadata: Record<string, unknown>;
  parent_ids: string[];
  data: Record<string, unknown>;
}

const STEP_NODES = new Set(["gate", "retrieve", "refuse", "answer"]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

/** JSON inválido ou sem `event`/`name`/`run_id` string → null (tolerância a
 * eventos futuros). Campos opcionais ausentes viram vazios. */
export function parseStreamEvent(data: string): StreamEvent | null {
  let parsed: unknown;
  try {
    parsed = JSON.parse(data);
  } catch {
    return null;
  }
  if (!isRecord(parsed)) return null;
  const { event, name, run_id, tags, metadata, parent_ids, data: payload } = parsed;
  if (typeof event !== "string" || typeof name !== "string" || typeof run_id !== "string") return null;
  return {
    event,
    name,
    run_id,
    tags: Array.isArray(tags) ? (tags as string[]) : [],
    metadata: isRecord(metadata) ? metadata : {},
    parent_ids: Array.isArray(parent_ids) ? (parent_ids as string[]) : [],
    data: isRecord(payload) ? payload : {},
  };
}

export async function* parseStreamEvents(stream: ReadableStream<Uint8Array>): AsyncGenerator<StreamEvent> {
  for await (const block of parseSSE(stream)) {
    const event = parseStreamEvent(block.data);
    if (event) yield event;
  }
}

export interface AskBody {
  input: { question: string };
  config: { run_id: string; configurable: { thread_id: string } };
}

/** Espelha `astream_events(input, config)`. thread_id = conversa (o cliente
 * gera; o servidor faz find-or-create). run_id = run do LangSmith. */
export function buildAskBody(question: string, threadId?: string): AskBody {
  return {
    input: { question },
    config: { run_id: crypto.randomUUID(), configurable: { thread_id: threadId ?? crypto.randomUUID() } },
  };
}

function isRoot(ev: StreamEvent): boolean {
  return ev.parent_ids.length === 0;
}

function isStepNode(ev: StreamEvent): boolean {
  return STEP_NODES.has(ev.name) && ev.metadata.langgraph_node === ev.name;
}

function stepDetail(name: string, output: unknown): Record<string, unknown> | undefined {
  if (!isRecord(output)) return undefined;
  if (name === "gate") return { retrieve: output.retrieve, degraded: output.degraded };
  if (name === "retrieve") return { kept: output.kept };
  return undefined;
}

function readCitations(output: unknown): Citation[] {
  const list = isRecord(output) ? output.citations : undefined;
  return Array.isArray(list) ? (list as Citation[]) : [];
}

function tokenText(chunk: unknown): string {
  return isRecord(chunk) && typeof chunk.content === "string" ? chunk.content : "";
}

/** Texto canônico da recusa: só do chunk `["updates", { refuse: { answer } }]`. */
function refusalText(chunk: unknown): string {
  if (!Array.isArray(chunk) || chunk.length !== 2 || chunk[0] !== "updates" || !isRecord(chunk[1])) return "";
  const refuse = chunk[1].refuse;
  return isRecord(refuse) && typeof refuse.answer === "string" ? refuse.answer : "";
}

function toolStatus(output: unknown): "ok" | "error" {
  return isRecord(output) && output.status === "error" ? "error" : "ok";
}

export async function* toAskEvents(events: AsyncIterable<StreamEvent>): AsyncGenerator<AskEvent> {
  for await (const ev of events) {
    switch (ev.event) {
      case "on_chain_start":
        if (isRoot(ev)) yield { type: "run_started", conversationId: String(ev.metadata.thread_id ?? "") };
        else if (isStepNode(ev)) yield { type: "step", name: ev.name, phase: "started" };
        break;
      case "on_chain_end":
        if (isRoot(ev)) {
          yield { type: "sources", citations: readCitations(ev.data.output) };
          yield { type: "done" };
        } else if (isStepNode(ev)) {
          const detail = stepDetail(ev.name, ev.data.output);
          yield detail ? { type: "step", name: ev.name, phase: "finished", detail } : { type: "step", name: ev.name, phase: "finished" };
        }
        break;
      case "on_chain_stream": {
        // Decisão 2 da spec: o frontend consome só `updates`; `values` é ignorado.
        if (!isRoot(ev)) break;
        const text = refusalText(ev.data.chunk);
        if (text) yield { type: "token", text };
        break;
      }
      case "on_chat_model_stream": {
        const text = tokenText(ev.data.chunk);
        if (text) yield { type: "token", text };
        break;
      }
      case "on_tool_start":
        // A tool é identificada pelo run_id: start e end da mesma execução o compartilham.
        yield { type: "tool_call_start", id: ev.run_id, name: ev.name };
        if (ev.data.input !== undefined) yield { type: "tool_call_args", id: ev.run_id, delta: JSON.stringify(ev.data.input) };
        yield { type: "tool_call_end", id: ev.run_id };
        break;
      case "on_tool_end":
      case "on_tool_error":
        yield { type: "tool_call_result", id: ev.run_id, status: toolStatus(ev.data.output) };
        break;
      case "on_chain_error":
        yield { type: "error", message: typeof ev.data.error === "string" && ev.data.error ? ev.data.error : "erro" };
        break;
      default:
        break;
    }
  }
}
