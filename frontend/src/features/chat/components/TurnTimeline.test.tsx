import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { ActivityItem } from "../../../hooks/useAskStream";
import { TurnTimeline } from "./TurnTimeline";

describe("TurnTimeline", () => {
  it("shows the waiting dots while there is no activity yet", () => {
    render(<TurnTimeline activity={[]} />);
    expect(screen.getByLabelText("Pensando")).toBeInTheDocument();
  });

  it("labels steps in Portuguese and shows the retrieval count", () => {
    const activity: ActivityItem[] = [
      { kind: "step", name: "gate", status: "done", detail: { retrieve: true, degraded: false } },
      { kind: "step", name: "retrieve", status: "done", detail: { kept: 4 } },
      { kind: "step", name: "answer", status: "running" },
    ];
    render(<TurnTimeline activity={activity} />);
    expect(screen.getByText("Entendendo a pergunta")).toBeInTheDocument();
    expect(screen.getByText("Buscando na base · 4 trechos")).toBeInTheDocument();
    expect(screen.getByText("Respondendo")).toBeInTheDocument();
    const items = screen.getAllByRole("listitem");
    expect(items[0]).toHaveAttribute("data-state", "done");
    expect(items[2]).toHaveAttribute("data-state", "running");
  });

  it("uses the singular for a single retrieved chunk and the refusal wording", () => {
    render(
      <TurnTimeline
        activity={[
          { kind: "step", name: "retrieve", status: "done", detail: { kept: 1 } },
          { kind: "step", name: "refuse", status: "done" },
        ]}
      />
    );
    expect(screen.getByText("Buscando na base · 1 trecho")).toBeInTheDocument();
    expect(screen.getByText("Nada na base cobre essa pergunta")).toBeInTheDocument();
  });

  it("shows the web search query but never the Notion page id", () => {
    const activity: ActivityItem[] = [
      { kind: "tool", id: "t1", name: "web_search", argsRaw: "", args: { query: "renovação PSP" }, status: "ok" },
      { kind: "tool", id: "t2", name: "fetch_notion_page", argsRaw: "", args: { page_id: "abc123-secret" }, status: "running" },
    ];
    render(<TurnTimeline activity={activity} />);
    expect(screen.getByText("Buscando na web: «renovação PSP»")).toBeInTheDocument();
    expect(screen.getByText("Lendo página do Notion")).toBeInTheDocument();
    expect(screen.queryByText(/abc123-secret/)).not.toBeInTheDocument();
  });

  it("marks a failed tool call", () => {
    render(
      <TurnTimeline
        activity={[{ kind: "tool", id: "t1", name: "web_search", argsRaw: "", status: "error" }]}
      />
    );
    const item = screen.getByRole("listitem");
    expect(item).toHaveAttribute("data-state", "error");
    expect(screen.getByText("falhou")).toBeInTheDocument();
  });
});
