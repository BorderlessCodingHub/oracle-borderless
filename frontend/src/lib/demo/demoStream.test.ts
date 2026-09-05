import { describe, it, expect } from "vitest";
import { demoStream } from "./demoStream";
import type { AskEvent } from "../types";

async function collect(input: { question: string; conversationId?: string }) {
  const events: AskEvent[] = [];
  for await (const e of demoStream(input)) events.push(e);
  return events;
}

describe("demoStream", () => {
  it("emits run_started, steps, tokens, sources, done on success", async () => {
    const events = await collect({ question: "qual a nomenclatura?" });
    expect(events[0]).toEqual({ type: "run_started", conversationId: "demo-new" });
    expect(events.some((e) => e.type === "step")).toBe(true);
    expect(events.some((e) => e.type === "token")).toBe(true);
    expect(events.some((e) => e.type === "sources")).toBe(true);
    expect(events.at(-1)?.type).toBe("done");

    // Assert strict relative ordering
    const types = events.map((e) => e.type);
    const firstToken = types.indexOf("token");
    const lastToken = types.lastIndexOf("token");
    const sourcesIdx = types.indexOf("sources");
    const doneIdx = types.indexOf("done");

    expect(types[0]).toBe("run_started"); // run_started first
    expect(firstToken).toBeGreaterThan(0); // tokens after run_started
    expect(sourcesIdx).toBeGreaterThan(lastToken); // sources after the last token
    expect(doneIdx).toBe(types.length - 1); // done last
    expect(sourcesIdx).toBeLessThan(doneIdx); // sources before done
  });

  it("emits an error path for the [demo-error] sentinel, terminal (no done)", async () => {
    const events = await collect({ question: "[demo-error]" });
    expect(events[0]).toEqual({ type: "run_started", conversationId: "demo-new" });
    expect(events.some((e) => e.type === "error")).toBe(true);
    expect(events.some((e) => e.type === "token")).toBe(false);
    expect(events.some((e) => e.type === "done")).toBe(false);
    expect(events.at(-1)?.type).toBe("error");
  });
});
