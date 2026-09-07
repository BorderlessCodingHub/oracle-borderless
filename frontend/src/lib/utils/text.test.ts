import { describe, expect, it } from "vitest";
import { stripHtml, toPlainText } from "./text";

describe("stripHtml", () => {
  it("removes HTML tags", () => {
    expect(stripHtml("<details><summary>x</summary>y</details>")).toBe("xy");
  });

  it("preserves math comparisons (does not treat < > as tags)", () => {
    expect(stripHtml("score < 60 e resultado > 0")).toBe("score < 60 e resultado > 0");
  });

  it("still removes real HTML tags including attributes", () => {
    expect(stripHtml('<a href="http://x">link</a>')).toBe("link");
    expect(stripHtml("<details><summary>x</summary>y</details>")).toBe("xy");
  });

  it("keeps comparisons intact through toPlainText", () => {
    const out = toPlainText("Se score < 60 então reprova; caso > 90, destaque.");
    expect(out).toContain("< 60");
    expect(out).toContain("> 90");
  });
});

describe("toPlainText", () => {
  it("strips markdown markup while keeping the words", () => {
    const result = toPlainText(
      "## Título\n\n**negrito** e *itálico*\n- item 1\n- item 2\n[link](http://x)"
    );
    expect(result).not.toMatch(/#/);
    expect(result).not.toMatch(/\*/);
    expect(result).not.toMatch(/^\s*-\s/m);
    expect(result).not.toMatch(/[[\]]/);
    expect(result).not.toMatch(/\(http/);
    expect(result).toContain("Título");
    expect(result).toContain("negrito");
    expect(result).toContain("item 1");
    expect(result).toContain("link");
  });

  it("strips stray HTML alongside markdown", () => {
    const result = toPlainText(
      "</details> <details> <summary>PSP x BASE</summary> A Base..."
    );
    expect(result).not.toMatch(/[<>]/);
    expect(result).toContain("PSP x BASE");
  });
});

// A interface já mostra as fontes no bloco recolhível ("N fontes"); o marcador
// que o modelo copia do contexto das ferramentas ("[Fonte: título — url]") não
// pode aparecer no corpo da resposta.
describe("stripSourceMarkers", () => {
  it("remove o marcador [Fonte: …] e a linha vazia que sobra", async () => {
    const { stripSourceMarkers } = await import("./text");
    const input =
      "O PSP é o programa premium.\n\n[Fonte: Offer Architecture, PSP — https://app.notion.com/p/Offer-Architecture-3288d655c88981668dc4dfd824c986f7]";
    expect(stripSourceMarkers(input)).toBe("O PSP é o programa premium.");
  });

  it("remove vários marcadores no meio do texto sem grudar os parágrafos", async () => {
    const { stripSourceMarkers } = await import("./text");
    const input = "Parágrafo 1.\n[Fonte: A — https://a]\n\nParágrafo 2.\n[Fonte: B — https://b]\n";
    expect(stripSourceMarkers(input)).toBe("Parágrafo 1.\n\nParágrafo 2.");
  });

  it("remove um marcador ainda incompleto no fim (streaming token a token)", async () => {
    const { stripSourceMarkers } = await import("./text");
    expect(stripSourceMarkers("Resposta.\n\n[Fonte: Offer Archi")).toBe("Resposta.");
  });

  it("não toca em colchetes comuns nem em links markdown", async () => {
    const { stripSourceMarkers } = await import("./text");
    const input = "Veja [o guia](https://x) e o item [1] da lista.";
    expect(stripSourceMarkers(input)).toBe(input);
  });
});
