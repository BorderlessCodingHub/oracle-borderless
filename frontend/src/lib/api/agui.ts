/** AG-UI no fio (ADR-0019): tipos dos eventos que consumimos, parser tolerante
 * e a tradução para o `AskEvent` interno. O hook e a UI não conhecem o
 * protocolo — só este módulo. */
import type { AskEvent, Citation } from "../types";
import { parseSSEData } from "./sse";

export type AgUiEvent =
  | { type: "RUN_STARTED"; threadId: string; runId: string }
  | { type: "RUN_FINISHED"; threadId: string; runId: string }
  | { type: "RUN_ERROR"; message: string; code?: string }
  | { type: "STEP_STARTED"; stepName: string }
  | { type: "STEP_FINISHED"; stepName: string }
  | { type: "TEXT_MESSAGE_START"; messageId: string; role: "assistant" }
  | { type: "TEXT_MESSAGE_CONTENT"; messageId: string; delta: string }
  | { type: "TEXT_MESSAGE_END"; messageId: string }
  | { type: "TOOL_CALL_START"; toolCallId: string; toolCallName: string; parentMessageId?: string }
  | { type: "TOOL_CALL_ARGS"; toolCallId: string; delta: string }
  | { type: "TOOL_CALL_END"; toolCallId: string }
  | { type: "TOOL_CALL_RESULT"; messageId: string; toolCallId: string; content: string; role?: "tool" }
  | { type: "CUSTOM"; name: string; value: unknown };

const KNOWN_TYPES = new Set<string>([
  "RUN_STARTED", "RUN_FINISHED", "RUN_ERROR",
  "STEP_STARTED", "STEP_FINISHED",
  "TEXT_MESSAGE_START", "TEXT_MESSAGE_CONTENT", "TEXT_MESSAGE_END",
  "TOOL_CALL_START", "TOOL_CALL_ARGS", "TOOL_CALL_END", "TOOL_CALL_RESULT",
  "CUSTOM",
]);

export const SOURCES_EVENT = "oracle.sources";
export const STEP_EVENT = "oracle.step";

/** JSON inválido ou tipo desconhecido → null (tolerância a eventos futuros). */
export function parseAgUiEvent(data: string): AgUiEvent | null {
  let parsed: unknown;
  try {
    parsed = JSON.parse(data);
  } catch {
    return null;
  }
  if (!parsed || typeof parsed !== "object") return null;
  const type = (parsed as { type?: unknown }).type;
  if (typeof type !== "string" || !KNOWN_TYPES.has(type)) return null;
  return parsed as AgUiEvent;
}

export async function* parseAgUiStream(stream: ReadableStream<Uint8Array>): AsyncGenerator<AgUiEvent> {
  for await (const data of parseSSEData(stream)) {
    const event = parseAgUiEvent(data);
    if (event) yield event;
  }
}

export interface RunAgentInput {
  threadId: string;
  runId: string;
  messages: Array<{ id: string; role: "user"; content: string }>;
  tools: never[];
  context: never[];
  forwardedProps: Record<string, never>;
}

/** threadId = conversa (o cliente gera; o servidor faz find-or-create).
 * runId = run do LangSmith. O protocolo exige tools/context/forwardedProps. */
export function buildRunAgentInput(question: string, threadId?: string): RunAgentInput {
  return {
    threadId: threadId ?? crypto.randomUUID(),
    runId: crypto.randomUUID(),
    messages: [{ id: crypto.randomUUID(), role: "user", content: question }],
    tools: [],
    context: [],
    forwardedProps: {},
  };
}

function isStepDetail(value: unknown, step: string): value is Record<string, unknown> {
  return !!value && typeof value === "object" && (value as { step?: unknown }).step === step;
}

function detailOf(value: Record<string, unknown>): Record<string, unknown> {
  const detail: Record<string, unknown> = {};
  for (const [key, v] of Object.entries(value)) if (key !== "step") detail[key] = v;
  return detail;
}

function resultStatus(content: string): "ok" | "error" {
  try {
    const parsed = JSON.parse(content) as { status?: unknown };
    return parsed?.status === "error" ? "error" : "ok";
  } catch {
    return "ok";
  }
}

function readCitations(value: unknown): Citation[] {
  const list = (value as { citations?: unknown } | null)?.citations;
  return Array.isArray(list) ? (list as Citation[]) : [];
}

/** STEP_FINISHED pode vir seguido de um CUSTOM oracle.step com o detalhe: os
 * dois viram um único `step finished`. O finished fica pendente até o próximo
 * evento (ou o fim do stream). */
export async function* toAskEvents(events: AsyncIterable<AgUiEvent>): AsyncGenerator<AskEvent> {
  let pending: string | null = null;
  for await (const ev of events) {
    if (pending !== null) {
      if (ev.type === "CUSTOM" && ev.name === STEP_EVENT && isStepDetail(ev.value, pending)) {
        yield { type: "step", name: pending, phase: "finished", detail: detailOf(ev.value) };
        pending = null;
        continue;
      }
      yield { type: "step", name: pending, phase: "finished" };
      pending = null;
    }
    switch (ev.type) {
      case "RUN_STARTED":
        yield { type: "run_started", conversationId: ev.threadId };
        break;
      case "STEP_STARTED":
        yield { type: "step", name: ev.stepName, phase: "started" };
        break;
      case "STEP_FINISHED":
        pending = ev.stepName;
        break;
      case "TEXT_MESSAGE_CONTENT":
        if (ev.delta) yield { type: "token", text: ev.delta };
        break;
      case "TOOL_CALL_START":
        yield { type: "tool_call_start", id: ev.toolCallId, name: ev.toolCallName };
        break;
      case "TOOL_CALL_ARGS":
        yield { type: "tool_call_args", id: ev.toolCallId, delta: ev.delta };
        break;
      case "TOOL_CALL_END":
        yield { type: "tool_call_end", id: ev.toolCallId };
        break;
      case "TOOL_CALL_RESULT":
        yield { type: "tool_call_result", id: ev.toolCallId, status: resultStatus(ev.content) };
        break;
      case "CUSTOM":
        if (ev.name === SOURCES_EVENT) yield { type: "sources", citations: readCitations(ev.value) };
        break;
      case "RUN_ERROR":
        yield { type: "error", message: ev.message || "erro" };
        break;
      case "RUN_FINISHED":
        yield { type: "done" };
        break;
      default:
        // TEXT_MESSAGE_START/END: o texto já chega pelos deltas.
        break;
    }
  }
  if (pending !== null) yield { type: "step", name: pending, phase: "finished" };
}
