import { describe, it, expect } from "vitest";
import { parseSSEData } from "./sse";

function streamOf(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const c of chunks) controller.enqueue(encoder.encode(c));
      controller.close();
    },
  });
}

async function collect(stream: ReadableStream<Uint8Array>) {
  const out: string[] = [];
  for await (const data of parseSSEData(stream)) out.push(data);
  return out;
}

describe("parseSSEData", () => {
  it("parses complete blocks, ignoring event:/id:/retry:", async () => {
    const events = await collect(
      streamOf([
        "event: conversation\ndata: {\"id\":\"abc\"}\n\n",
        "id: 1\ndata: {\"text\":\"oi\"}\nretry: 3000\n\n",
      ])
    );
    expect(events).toEqual(['{"id":"abc"}', '{"text":"oi"}']);
  });

  it("reassembles a block split across chunks", async () => {
    const events = await collect(streamOf(["da", 'ta: {"text":"x"}\n\n']));
    expect(events).toEqual(['{"text":"x"}']);
  });

  it("flushes a trailing block with no blank-line terminator when the stream ends", async () => {
    const events = await collect(streamOf(["data: {}"]));
    expect(events).toEqual(["{}"]);
  });

  it("joins multiple data: lines within one block", async () => {
    const events = await collect(streamOf(["data: line1\ndata: line2\n\n"]));
    expect(events).toEqual(["line1\nline2"]);
  });
});
