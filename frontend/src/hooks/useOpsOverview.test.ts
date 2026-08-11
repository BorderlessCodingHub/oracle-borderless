import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useOpsOverview } from "./useOpsOverview";

const overview = {
  window: "24h",
  knowledge: { documents_active: 42, documents_archived: 520, chunks: 260, sections: ["Bootcamps"] },
  sync: { job_name: null, status: null, started_at: null, finished_at: null, error: null },
  traces: { turns: 0, gate_retrieve: 0, gate_skip: 0, gate_degraded: 0, answers: 0, refusals: 0, errors: 0, avg_first_token_ms: null, max_first_token_ms: null, avg_engine_ms: null, max_engine_ms: null, avg_retrieval_kept: null, avg_best_distance: null },
  rag_top_k: 6,
  rag_max_distance: 0.55,
};

afterEach(() => vi.unstubAllGlobals());

describe("useOpsOverview", () => {
  it("loads the overview for the given window", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(overview))));
    const { result } = renderHook(() => useOpsOverview("24h"));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.overview?.knowledge.documents_active).toBe(42);
  });

  it("surfaces an error instead of throwing", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("nope", { status: 500 })));
    const { result } = renderHook(() => useOpsOverview("24h"));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.error).toBeTruthy();
    expect(result.current.overview).toBeNull();
  });
});
