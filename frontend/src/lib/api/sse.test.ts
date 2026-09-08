import { describe, it, expect } from "vitest";
import { parseSSE } from "./sse";

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
  const out: Array<{ event: string | null; data: string }> = [];
  for await (const block of parseSSE(stream)) out.push(block);
  return out;
}

describe("parseSSE", () => {
  it("reads event: and data: of complete blocks, ignoring id:/retry:", async () => {
    const blocks = await collect(
      streamOf([
        'event: on_chain_start\ndata: {"event":"on_chain_start"}\n\n',
        'id: 1\ndata: {"text":"oi"}\nretry: 3000\n\n',
      ])
    );
    expect(blocks).toEqual([
      { event: "on_chain_start", data: '{"event":"on_chain_start"}' },
      { event: null, data: '{"text":"oi"}' },
    ]);
  });

  it("reassembles a block split across chunks", async () => {
    const blocks = await collect(streamOf(["event: on_chat_mo", 'del_stream\nda', 'ta: {"text":"x"}\n\n']));
    expect(blocks).toEqual([{ event: "on_chat_model_stream", data: '{"text":"x"}' }]);
  });

  it("flushes a trailing block with no blank-line terminator when the stream ends", async () => {
    expect(await collect(streamOf(["data: {}"]))).toEqual([{ event: null, data: "{}" }]);
  });

  it("joins multiple data: lines within one block", async () => {
    expect(await collect(streamOf(["data: line1\ndata: line2\n\n"]))).toEqual([{ event: null, data: "line1\nline2" }]);
  });

  it("drops blocks without data:", async () => {
    expect(await collect(streamOf(["event: ping\n\n", ": comment\n\n"]))).toEqual([]);
  });
});
