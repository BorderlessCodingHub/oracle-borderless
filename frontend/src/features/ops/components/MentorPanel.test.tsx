import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { MentorInsights } from "../../../lib/types.ops";
import { MentorPanel } from "./MentorPanel";

const insights: MentorInsights = {
  gaps: [
    {
      lesson_id: "v1",
      program_slug: "base",
      question: "o que é autorregressão?",
      asked_at: "2026-01-01T12:00:00+00:00",
      user_email: "aluno@x.com",
    },
  ],
  engagement: [
    { lesson_id: "v1", turns: 3, distinct_users: 2, avg_citations: 2, gap_ratio: 1 / 3 },
  ],
};

describe("MentorPanel", () => {
  it("mostra a pergunta sem cobertura no backlog", () => {
    render(<MentorPanel insights={insights} />);
    expect(screen.getByText("o que é autorregressão?")).toBeInTheDocument();
  });

  it("mostra a linha de retenção da aula na tabela", () => {
    render(<MentorPanel insights={insights} />);
    const cell = screen.getByRole("cell", { name: "v1" });
    const row = cell.closest("tr");
    expect(row).not.toBeNull();
    expect(row!.textContent).toContain("3");
    expect(row!.textContent).toContain("2");
  });

  it("não quebra sem dados ainda carregados", () => {
    render(<MentorPanel insights={null} />);
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
});
