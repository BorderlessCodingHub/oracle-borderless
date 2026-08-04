// @vitest-environment node
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { ARCHITECTURE_MAP } from "./architectureMap";

const REPO_ROOT = resolve(fileURLToPath(new URL(".", import.meta.url)), "../../../..");
const boxes = ARCHITECTURE_MAP.flatMap((band) => band.boxes);

describe("ARCHITECTURE_MAP", () => {
  it("declares at least one band with boxes", () => {
    expect(ARCHITECTURE_MAP.length).toBeGreaterThan(0);
    expect(boxes.length).toBeGreaterThan(0);
  });

  it("every declared file exists in the repository", () => {
    // Esta é a amarra do "mapa honesto": mudou o pipeline, muda o mapa.
    const missing = boxes
      .flatMap((box) => box.files.map((file) => ({ id: box.id, file })))
      .filter(({ file }) => !existsSync(resolve(REPO_ROOT, file)));

    expect(missing).toEqual([]);
  });

  it("has unique box ids", () => {
    const ids = boxes.map((b) => b.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("gives every box a label and a description in pt-BR", () => {
    for (const box of boxes) {
      expect(box.label.length).toBeGreaterThan(0);
      expect(box.description.length).toBeGreaterThan(0);
    }
  });
});
