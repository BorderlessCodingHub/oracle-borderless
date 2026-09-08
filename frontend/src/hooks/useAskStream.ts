import { useCallback, useRef, useState } from "react";
import type { AskEvent, AskInput, Citation } from "../lib/types";
import { askStream } from "../data/source";

export type AskStatus = "idle" | "thinking" | "streaming" | "done" | "error";

export type StepItem = {
  kind: "step";
  name: string;
  status: "running" | "done";
  detail?: Record<string, unknown>;
};

export type ToolItem = {
  kind: "tool";
  id: string;
  name: string;
  /** JSON dos argumentos como chega, em fragmentos. */
  argsRaw: string;
  /** Parseado no `tool_call_end`; undefined se o JSON não fechar. */
  args?: Record<string, unknown>;
  status: "pending" | "running" | "ok" | "error";
};

/** Linha do tempo do turno em ordem de chegada — passos e tool calls
 * intercalados ("Respondendo" → "Buscando na web" → "Respondendo" continua). */
export type ActivityItem = StepItem | ToolItem;

function parseArgs(raw: string): Record<string, unknown> | undefined {
  try {
    const parsed = JSON.parse(raw) as unknown;
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? (parsed as Record<string, unknown>)
      : undefined;
  } catch {
    return undefined;
  }
}

function updateTool(prev: ActivityItem[], id: string, patch: (t: ToolItem) => ToolItem): ActivityItem[] {
  const idx = prev.findIndex((i) => i.kind === "tool" && i.id === id);
  if (idx === -1) return prev;
  const next = [...prev];
  next[idx] = patch(next[idx] as ToolItem);
  return next;
}

/** Redutor puro: um AskEvent → nova lista. Devolve a MESMA referência quando o
 * evento não é de atividade ou não encontra o item, para não re-renderizar à toa. */
export function applyActivity(prev: ActivityItem[], evt: AskEvent): ActivityItem[] {
  switch (evt.type) {
    case "step": {
      if (evt.phase === "started") {
        return [...prev, { kind: "step", name: evt.name, status: "running" }];
      }
      let idx = -1;
      for (let i = prev.length - 1; i >= 0; i--) {
        const item = prev[i];
        if (item.kind === "step" && item.name === evt.name && item.status === "running") {
          idx = i;
          break;
        }
      }
      if (idx === -1) {
        return [...prev, { kind: "step", name: evt.name, status: "done", detail: evt.detail }];
      }
      const next = [...prev];
      next[idx] = { ...(next[idx] as StepItem), status: "done", detail: evt.detail };
      return next;
    }
    case "tool_call_start":
      return [...prev, { kind: "tool", id: evt.id, name: evt.name, argsRaw: "", status: "pending" }];
    case "tool_call_args":
      return updateTool(prev, evt.id, (t) => ({ ...t, argsRaw: t.argsRaw + evt.delta }));
    case "tool_call_end":
      return updateTool(prev, evt.id, (t) => ({ ...t, args: parseArgs(t.argsRaw), status: "running" }));
    case "tool_call_result":
      return updateTool(prev, evt.id, (t) => ({ ...t, status: evt.status }));
    default:
      return prev;
  }
}

export function useAskStream() {
  const [status, setStatus] = useState<AskStatus>("idle");
  const [answer, setAnswer] = useState("");
  const [citations, setCitations] = useState<Citation[]>([]);
  const [activity, setActivity] = useState<ActivityItem[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  // Generation guard: bumped on every ask()/reset() so a superseded run's
  // events (from a prior in-flight async-generator loop) can be told apart
  // from the current one and dropped instead of corrupting shared state.
  const genRef = useRef(0);

  const reset = useCallback(() => {
    genRef.current++;
    setStatus("idle");
    setAnswer("");
    setCitations([]);
    setActivity([]);
    setErrorMessage(null);
  }, []);

  const ask = useCallback(async (input: AskInput) => {
    const myGen = ++genRef.current;
    setStatus("thinking");
    setAnswer("");
    setCitations([]);
    setActivity([]);
    setErrorMessage(null);
    // O fio termina no on_chain_end do raiz ou em on_chain_error. Se o stream acabar sem
    // nenhum dos dois (queda de conexão, proxy), é erro — não um "streaming"
    // preso para sempre.
    let terminated = false;
    try {
      for await (const evt of askStream(input)) {
        if (genRef.current !== myGen) return;
        switch (evt.type) {
          case "run_started":
            setConversationId(evt.conversationId);
            break;
          case "token":
            setStatus("streaming");
            setAnswer((prev) => prev + evt.text);
            break;
          case "sources":
            setCitations(evt.citations);
            break;
          case "error":
            terminated = true;
            setErrorMessage(evt.message);
            setStatus("error");
            break;
          case "done":
            terminated = true;
            setStatus((s) => (s === "error" ? "error" : "done"));
            break;
          default:
            setActivity((prev) => applyActivity(prev, evt));
        }
      }
      if (genRef.current !== myGen) return;
      if (!terminated) {
        setErrorMessage("conexão interrompida");
        setStatus("error");
      }
    } catch (e) {
      if (genRef.current !== myGen) return;
      setErrorMessage(e instanceof Error ? e.message : "erro inesperado");
      setStatus("error");
    }
  }, []);

  return { status, answer, citations, activity, conversationId, errorMessage, ask, reset };
}
