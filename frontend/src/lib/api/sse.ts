/** Lê um stream SSE e devolve `{ event, data }` de cada bloco.
 *
 * O fio do ADR-0021 usa a linha `event:` (nome do StreamEvent) e `data:` (o
 * StreamEvent em JSON). `id:` e `retry:` são ignorados. Linhas `data:`
 * múltiplas no mesmo bloco são unidas com "\n". Bloco sem `data:` é descartado. */
export interface SSEBlock {
  event: string | null;
  data: string;
}

export async function* parseSSE(stream: ReadableStream<Uint8Array>): AsyncGenerator<SSEBlock> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() ?? "";
    for (const part of parts) {
      const block = readBlock(part);
      if (block !== null) yield block;
    }
  }
  const tail = readBlock(buffer);
  if (tail !== null) yield tail;
}

function readBlock(block: string): SSEBlock | null {
  let event: string | null = null;
  const data: string[] = [];
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) data.push(line.slice(5).trim());
  }
  return data.length ? { event, data: data.join("\n") } : null;
}
