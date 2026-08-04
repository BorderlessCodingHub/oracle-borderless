// @vitest-environment node
import { readdirSync, readFileSync, statSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { join, resolve, relative } from "node:path";
import { describe, expect, it } from "vitest";

// Por quê este teste existe: uma cor crua (#hex ou rgb/rgba literal) num
// *.module.css assume um fundo fixo — normalmente o escuro, porque é o modo
// histórico do produto. Ela renderiza bem enquanto :root é o único bloco de
// tokens, mas quebra silenciosamente assim que alguém entra em modo claro
// (texto apagado, borda invisível, ícone que some). A varredura do plano de
// tema claro/escuro (docs/superpowers/plans/2026-08-04-tema-claro-escuro.md,
// Task 3 Step 10) rodou à mão uma vez; isto a promove a invariante permanente
// para que o próximo componente novo não reintroduza o problema.
const SRC_ROOT = resolve(fileURLToPath(new URL(".", import.meta.url)), "..");

// Exceções sancionadas: valores fixos de propósito, iguais nos dois temas.
// - #06231b: tinta escura sobre fundo saturado (gradiente / esmeralda).
// - rgba(255, 255, 255, .10): override local de --border em .ctaCard
//   (LandingPage.module.css) — o card é escuro nos dois modos, então a borda
//   não pode seguir o --border do tema claro (ver fix 3 do review de tema).
const ALLOWED = new Set(["#06231b", "rgba(255, 255, 255, .10)"]);

const COLOR_RE = /#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\)/g;

type Violation = { file: string; line: number; match: string };

function walkModuleCssFiles(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    const stat = statSync(full);
    if (stat.isDirectory()) {
      walkModuleCssFiles(full, out);
    } else if (entry.endsWith(".module.css")) {
      out.push(full);
    }
  }
  return out;
}

function findViolations(): Violation[] {
  const violations: Violation[] = [];
  for (const file of walkModuleCssFiles(SRC_ROOT)) {
    const lines = readFileSync(file, "utf-8").split("\n");
    lines.forEach((lineText, idx) => {
      const matches = lineText.match(COLOR_RE);
      if (!matches) return;
      for (const match of matches) {
        if (ALLOWED.has(match.toLowerCase())) continue;
        violations.push({ file: relative(SRC_ROOT, file), line: idx + 1, match });
      }
    });
  }
  return violations;
}

describe("no-raw-colors invariant", () => {
  it("não deixa hex/rgba cru entrar em *.module.css fora de #06231b", () => {
    const violations = findViolations();

    if (violations.length > 0) {
      const details = violations.map((v) => `  ${v.file}:${v.line} -> ${v.match}`).join("\n");
      throw new Error(
        `Cor crua fora da lista permitida (${[...ALLOWED].join(", ")}) em *.module.css:\n${details}\n` +
          "Troque por um token semântico de src/styles/tokens.css (ou pare e reporte se não houver um equivalente)."
      );
    }

    expect(violations).toEqual([]);
  });
});
