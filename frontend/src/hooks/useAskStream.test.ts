import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import type { AskEvent } from "../lib/types";

const scenario = vi.hoisted(() => ({ events: [] as AskEvent[] }));
// Gate for the superseded-run test: the first ask()'s generator awaits this
// promise before yielding its later (stale) events, so we can start the
// second ask() while the first is still "in flight" and only then let the
// first run's remaining events attempt to land.
const gate = vi.hoisted(() => ({
  promise: Promise.resolve() as Promise<void>,
  resolve: (() => {}) as () => void,
}));

vi.mock("../data/source", () => ({
  isDemo: true,
  askStream: async function* (input: { question: string }) {
    if (input.question === "first (gated)") {
      yield { type: "run_started", conversationId: "stale-convo" } as AskEvent;
      yield { type: "token", text: "STALE_TOKEN " } as AskEvent;
      await gate.promise;
      yield { type: "token", text: "should-not-appear" } as AskEvent;
      yield { type: "done" } as AskEvent;
      return;
    }
    for (const e of scenario.events) yield e;
  },
}));

import { useAskStream, applyActivity, type ActivityItem } from "./useAskStream";

beforeEach(() => {
  scenario.events = [];
});

describe("useAskStream", () => {
  it("moves through thinking → streaming → done and accumulates tokens + citations", async () => {
    scenario.events = [
      { type: "run_started", conversationId: "c9" },
      { type: "token", text: "olá " },
      { type: "token", text: "mundo" },
      { type: "sources", citations: [{ source_type: "SOP", title: "T", url: "https://x", snippet: "s" }] },
      { type: "done" },
    ];
    const { result } = renderHook(() => useAskStream());
    await act(async () => {
      await result.current.ask({ question: "oi" });
    });
    await waitFor(() => expect(result.current.status).toBe("done"));
    expect(result.current.answer).toBe("olá mundo");
    expect(result.current.conversationId).toBe("c9");
    expect(result.current.citations).toHaveLength(1);
  });

  it("enters error status on an error event", async () => {
    scenario.events = [
      { type: "run_started", conversationId: "c9" },
      { type: "error", message: "falhou" },
    ];
    const { result } = renderHook(() => useAskStream());
    await act(async () => {
      await result.current.ask({ question: "[demo-error]" });
    });
    await waitFor(() => expect(result.current.status).toBe("error"));
    expect(result.current.errorMessage).toBe("falhou");
  });

  it("a second ask() supersedes a first still-running one; the stale run's later events are dropped", async () => {
    gate.promise = new Promise<void>((resolve) => {
      gate.resolve = resolve;
    });
    scenario.events = [
      { type: "run_started", conversationId: "c-second" },
      { type: "token", text: "second answer" },
      { type: "done" },
    ];
    const { result } = renderHook(() => useAskStream());

    let firstRunPromise!: Promise<void>;
    await act(async () => {
      // Not awaited: this run gates before its final events, staying
      // "in flight" while we start (and finish) a second, superseding run.
      firstRunPromise = result.current.ask({ question: "first (gated)" });
      await Promise.resolve();
      await Promise.resolve();
    });

    // The first run's pre-gate events landed normally (no supersession yet).
    expect(result.current.conversationId).toBe("stale-convo");
    expect(result.current.answer).toBe("STALE_TOKEN ");

    await act(async () => {
      await result.current.ask({ question: "second" });
    });

    await waitFor(() => expect(result.current.status).toBe("done"));
    expect(result.current.answer).toBe("second answer");
    expect(result.current.conversationId).toBe("c-second");

    // Release the stale run's remaining events now that it has been
    // superseded; they must be dropped rather than clobbering state.
    await act(async () => {
      gate.resolve();
      await firstRunPromise;
    });

    expect(result.current.status).toBe("done");
    expect(result.current.answer).toBe("second answer");
    expect(result.current.conversationId).toBe("c-second");
  });

  it("builds the activity timeline in arrival order, with steps and tool calls interleaved", async () => {
    scenario.events = [
      { type: "run_started", conversationId: "c1" },
      { type: "step", name: "gate", phase: "started" },
      { type: "step", name: "gate", phase: "finished", detail: { retrieve: true, degraded: false } },
      { type: "step", name: "retrieve", phase: "started" },
      { type: "step", name: "retrieve", phase: "finished", detail: { kept: 4 } },
      { type: "step", name: "answer", phase: "started" },
      { type: "tool_call_start", id: "t1", name: "web_search" },
      { type: "tool_call_args", id: "t1", delta: '{"query":' },
      { type: "tool_call_args", id: "t1", delta: '"psp"}' },
      { type: "tool_call_end", id: "t1" },
      { type: "tool_call_result", id: "t1", status: "ok" },
      { type: "token", text: "resposta" },
      { type: "step", name: "answer", phase: "finished" },
      { type: "sources", citations: [] },
      { type: "done" },
    ];
    const { result } = renderHook(() => useAskStream());
    await act(async () => {
      await result.current.ask({ question: "oi" });
    });
    await waitFor(() => expect(result.current.status).toBe("done"));

    expect(result.current.activity).toEqual([
      { kind: "step", name: "gate", status: "done", detail: { retrieve: true, degraded: false } },
      { kind: "step", name: "retrieve", status: "done", detail: { kept: 4 } },
      { kind: "step", name: "answer", status: "done", detail: undefined },
      { kind: "tool", id: "t1", name: "web_search", argsRaw: '{"query":"psp"}', args: { query: "psp" }, status: "ok" },
    ]);
  });

  it("a stream that ends without done or error is reported as a broken connection", async () => {
    scenario.events = [
      { type: "run_started", conversationId: "c1" },
      { type: "token", text: "parcial" },
    ];
    const { result } = renderHook(() => useAskStream());
    await act(async () => {
      await result.current.ask({ question: "oi" });
    });
    await waitFor(() => expect(result.current.status).toBe("error"));
    expect(result.current.errorMessage).toBe("conexão interrompida");
  });

  it("reset() clears the activity", async () => {
    scenario.events = [
      { type: "run_started", conversationId: "c1" },
      { type: "step", name: "gate", phase: "started" },
      { type: "done" },
    ];
    const { result } = renderHook(() => useAskStream());
    await act(async () => {
      await result.current.ask({ question: "oi" });
    });
    expect(result.current.activity).toHaveLength(1);
    act(() => result.current.reset());
    expect(result.current.activity).toEqual([]);
  });
});

describe("applyActivity", () => {
  it("a finished step without a prior started enters already done", () => {
    expect(applyActivity([], { type: "step", name: "gate", phase: "finished", detail: { retrieve: false } })).toEqual([
      { kind: "step", name: "gate", status: "done", detail: { retrieve: false } },
    ]);
  });

  it("tool call lifecycle: pending → running (args parsed) → ok/error", () => {
    let items: ActivityItem[] = applyActivity([], { type: "tool_call_start", id: "t1", name: "fetch_notion_page" });
    expect(items).toEqual([{ kind: "tool", id: "t1", name: "fetch_notion_page", argsRaw: "", status: "pending" }]);
    items = applyActivity(items, { type: "tool_call_args", id: "t1", delta: '{"page_id":"abc"}' });
    items = applyActivity(items, { type: "tool_call_end", id: "t1" });
    expect(items[0]).toMatchObject({ status: "running", args: { page_id: "abc" } });
    items = applyActivity(items, { type: "tool_call_result", id: "t1", status: "error" });
    expect(items[0]).toMatchObject({ status: "error" });
  });

  it("events for unknown tool ids and non-activity events leave the list untouched", () => {
    const items: ActivityItem[] = [{ kind: "step", name: "gate", status: "running" }];
    expect(applyActivity(items, { type: "tool_call_args", id: "ghost", delta: "x" })).toBe(items);
    expect(applyActivity(items, { type: "token", text: "x" })).toBe(items);
  });

  it("unparseable args stay undefined but the tool still runs", () => {
    let items: ActivityItem[] = applyActivity([], { type: "tool_call_start", id: "t1", name: "web_search" });
    items = applyActivity(items, { type: "tool_call_args", id: "t1", delta: "{oops" });
    items = applyActivity(items, { type: "tool_call_end", id: "t1" });
    expect(items[0]).toMatchObject({ status: "running", args: undefined, argsRaw: "{oops" });
  });
});
