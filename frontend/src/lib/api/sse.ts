/** Lê um stream SSE e devolve o payload `data:` de cada bloco.
 *
 * O AG-UI põe tudo no JSON (ADR-0019): `event:`, `id:` e `retry:` são
 * ignorados, como o protocolo pede. Linhas `data:` múltiplas no mesmo bloco
 * são unidas com "\n". */
export async function* parseSSEData(
  stream: ReadableStream<Uint8Array>
): AsyncGenerator<string> {
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
      const data = readData(part);
      if (data !== null) yield data;
    }
  }
  const tail = readData(buffer);
  if (tail !== null) yield tail;
}

function readData(block: string): string | null {
  const lines = block
    .split("\n")
    .filter((line) => line.startsWith("data:"))
    .map((line) => line.slice(5).trim());
  return lines.length ? lines.join("\n") : null;
}
