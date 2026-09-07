// @vitest-environment node
import { describe, expect, it } from "vitest";
import type { AskEvent } from "../types";
import { buildRunAgentInput, parseAgUiEvent, toAskEvents, type AgUiEvent } from "./agui";

async function* from(events: AgUiEvent[]): AsyncGenerator<AgUiEvent> {
  for (const e of events) yield e;
}

async function collect(events: AgUiEvent[]): Promise<AskEvent[]> {
  const out: AskEvent[] = [];
  for await (const e of toAskEvents(from(events))) out.push(e);
  return out;
}

describe("parseAgUiEvent", () => {
  it("parses a camelCase AG-UI event", () => {
    expect(parseAgUiEvent('{"type":"STEP_STARTED","stepName":"gate"}')).toEqual({ type: "STEP_STARTED", stepName: "gate" });
  });

  it("drops malformed JSON and unknown types", () => {
    expect(parseAgUiEvent("{not json")).toBeNull();
    expect(parseAgUiEvent('{"type":"SOMETHING_NEW","x":1}')).toBeNull();
    expect(parseAgUiEvent('"a string"')).toBeNull();
  });
});

describe("buildRunAgentInput", () => {
  it("uses the given threadId or mints one, always with a fresh runId and empty protocol fields", () => {
    const withThread = buildRunAgentInput("oi", "thread-1");
    expect(withThread.threadId).toBe("thread-1");
    expect(withThread.runId).toMatch(/[0-9a-f-]{36}/);
    expect(withThread.messages).toEqual([{ id: expect.any(String), role: "user", content: "oi" }]);
    expect(withThread.tools).toEqual([]);
    expect(withThread.context).toEqual([]);
    expect(withThread.forwardedProps).toEqual({});

    const fresh = buildRunAgentInput("oi");
    expect(fresh.threadId).toMatch(/[0-9a-f-]{36}/);
    expect(fresh.runId).not.toBe(fresh.threadId);
  });
});

describe("toAskEvents", () => {
  it("translates the happy path in order", async () => {
    const out = await collect([
      { type: "RUN_STARTED", threadId: "t1", runId: "r1" },
      { type: "STEP_STARTED", stepName: "gate" },
      { type: "STEP_FINISHED", stepName: "gate" },
      { type: "CUSTOM", name: "oracle.step", value: { step: "gate", retrieve: true, degraded: false } },
      { type: "TEXT_MESSAGE_START", messageId: "m1", role: "assistant" },
      { type: "TEXT_MESSAGE_CONTENT", messageId: "m1", delta: "olá" },
      { type: "TEXT_MESSAGE_END", messageId: "m1" },
      { type: "CUSTOM", name: "oracle.sources", value: { citations: [{ source_type: "notion", title: "T", url: "u", snippet: "s" }] } },
      { type: "RUN_FINISHED", threadId: "t1", runId: "r1" },
    ]);

    expect(out).toEqual([
      { type: "run_started", conversationId: "t1" },
      { type: "step", name: "gate", phase: "started" },
      { type: "step", name: "gate", phase: "finished", detail: { retrieve: true, degraded: false } },
      { type: "token", text: "olá" },
      { type: "sources", citations: [{ source_type: "notion", title: "T", url: "u", snippet: "s" }] },
      { type: "done" },
    ]);
  });

  it("a STEP_FINISHED without a following oracle.step is released on the next event", async () => {
    const out = await collect([
      { type: "STEP_FINISHED", stepName: "answer" },
      { type: "TEXT_MESSAGE_CONTENT", messageId: "m1", delta: "x" },
    ]);
    expect(out).toEqual([
      { type: "step", name: "answer", phase: "finished" },
      { type: "token", text: "x" },
    ]);
  });

  it("a trailing STEP_FINISHED is flushed when the stream ends", async () => {
    expect(await collect([{ type: "STEP_FINISHED", stepName: "answer" }])).toEqual([
      { type: "step", name: "answer", phase: "finished" },
    ]);
  });

  it("an oracle.step for a different step does not fuse", async () => {
    const out = await collect([
      { type: "STEP_FINISHED", stepName: "gate" },
      { type: "CUSTOM", name: "oracle.step", value: { step: "retrieve", kept: 2 } },
    ]);
    expect(out).toEqual([{ type: "step", name: "gate", phase: "finished" }]);
  });

  it("translates tool calls and reads the status out of TOOL_CALL_RESULT.content", async () => {
    const out = await collect([
      { type: "TOOL_CALL_START", toolCallId: "c1", toolCallName: "web_search", parentMessageId: "m1" },
      { type: "TOOL_CALL_ARGS", toolCallId: "c1", delta: '{"query":' },
      { type: "TOOL_CALL_ARGS", toolCallId: "c1", delta: '"psp"}' },
      { type: "TOOL_CALL_END", toolCallId: "c1" },
      { type: "TOOL_CALL_RESULT", messageId: "mt", toolCallId: "c1", content: '{"status":"error"}', role: "tool" },
    ]);
    expect(out).toEqual([
      { type: "tool_call_start", id: "c1", name: "web_search" },
      { type: "tool_call_args", id: "c1", delta: '{"query":' },
      { type: "tool_call_args", id: "c1", delta: '"psp"}' },
      { type: "tool_call_end", id: "c1" },
      { type: "tool_call_result", id: "c1", status: "error" },
    ]);
  });

  it("RUN_ERROR becomes error and is terminal (no done)", async () => {
    const out = await collect([
      { type: "RUN_STARTED", threadId: "t1", runId: "r1" },
      { type: "RUN_ERROR", message: "erro ao gerar a resposta" },
    ]);
    expect(out).toEqual([
      { type: "run_started", conversationId: "t1" },
      { type: "error", message: "erro ao gerar a resposta" },
    ]);
  });
});
