// @vitest-environment node
import { describe, expect, it } from "vitest";
import type { AskEvent } from "../types";
import { buildAskBody, parseStreamEvent, toAskEvents, type StreamEvent } from "./streamEvents";

const ROOT = "LangGraph";

function ev(partial: Partial<StreamEvent> & { event: string; name: string }): StreamEvent {
  return {
    run_id: "r",
    tags: [],
    metadata: { thread_id: "t1" },
    parent_ids: ["root"],
    data: {},
    ...partial,
  };
}

function root(event: string, data: Record<string, unknown> = {}): StreamEvent {
  return ev({ event, name: ROOT, parent_ids: [], data, run_id: "run-1" });
}

function node(event: string, name: string, data: Record<string, unknown> = {}): StreamEvent {
  return ev({ event, name, metadata: { thread_id: "t1", langgraph_node: name }, data });
}

async function* from(events: StreamEvent[]): AsyncGenerator<StreamEvent> {
  for (const e of events) yield e;
}

async function collect(events: StreamEvent[]): Promise<AskEvent[]> {
  const out: AskEvent[] = [];
  for await (const e of toAskEvents(from(events))) out.push(e);
  return out;
}

describe("parseStreamEvent", () => {
  it("parses a StreamEvent with the seven fields", () => {
    const raw = '{"event":"on_chain_start","name":"gate","run_id":"r","tags":[],"metadata":{"langgraph_node":"gate"},"parent_ids":["x"],"data":{}}';
    expect(parseStreamEvent(raw)).toEqual({
      event: "on_chain_start", name: "gate", run_id: "r", tags: [], metadata: { langgraph_node: "gate" }, parent_ids: ["x"], data: {},
    });
  });

  it("drops malformed JSON and payloads without event/name/run_id", () => {
    expect(parseStreamEvent("{not json")).toBeNull();
    expect(parseStreamEvent('{"name":"x","run_id":"r"}')).toBeNull();
    expect(parseStreamEvent('{"event":"on_chain_start","run_id":"r"}')).toBeNull();
    expect(parseStreamEvent('"a string"')).toBeNull();
  });

  it("fills missing optional fields with empty values", () => {
    expect(parseStreamEvent('{"event":"on_custom_event","name":"x","run_id":"r"}')).toEqual({
      event: "on_custom_event", name: "x", run_id: "r", tags: [], metadata: {}, parent_ids: [], data: {},
    });
  });
});

describe("buildAskBody", () => {
  it("mirrors astream_events(input, config): question, run_id and thread_id", () => {
    const withThread = buildAskBody("oi", "thread-1");
    expect(withThread).toEqual({
      input: { question: "oi" },
      config: { run_id: expect.stringMatching(/[0-9a-f-]{36}/), configurable: { thread_id: "thread-1" } },
    });

    const fresh = buildAskBody("oi");
    expect(fresh.config.configurable.thread_id).toMatch(/[0-9a-f-]{36}/);
    expect(fresh.config.run_id).not.toBe(fresh.config.configurable.thread_id);
  });
});

describe("toAskEvents", () => {
  it("translates the happy path in order", async () => {
    const citations = [{ source_type: "notion", title: "T", url: "u", snippet: "s" }];
    const out = await collect([
      root("on_chain_start"),
      root("on_chain_stream", { chunk: ["values", { kept: 0 }] }),
      node("on_chain_start", "gate"),
      node("on_chain_end", "gate", { output: { retrieve: true, degraded: false } }),
      root("on_chain_stream", { chunk: ["updates", { gate: { retrieve: true, degraded: false } }] }),
      node("on_chain_start", "retrieve"),
      node("on_chain_end", "retrieve", { output: { kept: 2 } }),
      node("on_chain_start", "answer"),
      ev({ event: "on_chat_model_stream", name: "ChatAnthropic", metadata: { thread_id: "t1", langgraph_node: "answer" }, data: { chunk: { content: "olá", id: "m" } } }),
      ev({ event: "on_chat_model_stream", name: "ChatAnthropic", metadata: { thread_id: "t1", langgraph_node: "answer" }, data: { chunk: { content: "", id: "m" } } }),
      node("on_chain_end", "answer", { output: { outcome: "answer", citations } }),
      root("on_chain_end", { output: { outcome: "answer", citations } }),
    ]);

    expect(out).toEqual([
      { type: "run_started", conversationId: "t1" },
      { type: "step", name: "gate", phase: "started" },
      { type: "step", name: "gate", phase: "finished", detail: { retrieve: true, degraded: false } },
      { type: "step", name: "retrieve", phase: "started" },
      { type: "step", name: "retrieve", phase: "finished", detail: { kept: 2 } },
      { type: "step", name: "answer", phase: "started" },
      { type: "token", text: "olá" },
      { type: "step", name: "answer", phase: "finished" },
      { type: "sources", citations },
      { type: "done" },
    ]);
  });

  it("reads the refusal text from the updates chunk only, not from the node end nor from values", async () => {
    const out = await collect([
      node("on_chain_start", "refuse"),
      node("on_chain_end", "refuse", { output: { answer: "Não encontrei.", citations: [], outcome: "refusal" } }),
      root("on_chain_stream", { chunk: ["updates", { refuse: { answer: "Não encontrei.", citations: [], outcome: "refusal" } }] }),
      root("on_chain_stream", { chunk: ["values", { answer: "Não encontrei.", kept: 0 }] }),
      root("on_chain_end", { output: { outcome: "refusal", citations: [] } }),
    ]);
    expect(out).toEqual([
      { type: "step", name: "refuse", phase: "started" },
      { type: "step", name: "refuse", phase: "finished" },
      { type: "token", text: "Não encontrei." },
      { type: "sources", citations: [] },
      { type: "done" },
    ]);
  });

  it("ignores node events whose name is not a step node or whose langgraph_node differs", async () => {
    const out = await collect([
      ev({ event: "on_chain_start", name: "should_retrieve", metadata: { thread_id: "t1", langgraph_node: "gate" } }),
      ev({ event: "on_chain_start", name: "tools", metadata: { thread_id: "t1", langgraph_node: "tools" } }),
      ev({ event: "on_chain_end", name: "__start__", metadata: { thread_id: "t1", langgraph_node: "__start__" } }),
    ]);
    expect(out).toEqual([]);
  });

  it("translates tools: start (+args when input present) then end/error with the status, keyed by run_id", async () => {
    const out = await collect([
      ev({ event: "on_tool_start", name: "web_search", run_id: "tool-1", metadata: { thread_id: "t1", langgraph_node: "tools" }, data: { input: { query: "psp" } } }),
      ev({ event: "on_tool_end", name: "web_search", run_id: "tool-1", metadata: { thread_id: "t1", langgraph_node: "tools" }, data: { output: { status: "ok", tool_call_id: "c1" } } }),
      ev({ event: "on_tool_start", name: "fetch_notion_page", run_id: "tool-2", metadata: { thread_id: "t1", langgraph_node: "tools" }, data: {} }),
      ev({ event: "on_tool_error", name: "fetch_notion_page", run_id: "tool-2", metadata: { thread_id: "t1", langgraph_node: "tools" }, data: { output: { status: "error", tool_call_id: "c2" } } }),
    ]);
    expect(out).toEqual([
      { type: "tool_call_start", id: "tool-1", name: "web_search" },
      { type: "tool_call_args", id: "tool-1", delta: '{"query":"psp"}' },
      { type: "tool_call_end", id: "tool-1" },
      { type: "tool_call_result", id: "tool-1", status: "ok" },
      { type: "tool_call_start", id: "tool-2", name: "fetch_notion_page" },
      { type: "tool_call_end", id: "tool-2" },
      { type: "tool_call_result", id: "tool-2", status: "error" },
    ]);
  });

  it("on_chain_error becomes error and is terminal (no done)", async () => {
    const out = await collect([
      root("on_chain_start"),
      root("on_chain_error", { error: "erro ao gerar a resposta" }),
    ]);
    expect(out).toEqual([
      { type: "run_started", conversationId: "t1" },
      { type: "error", message: "erro ao gerar a resposta" },
    ]);
  });
});
