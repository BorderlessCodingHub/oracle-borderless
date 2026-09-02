import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Citation } from "../../../lib/types";
import { CitationsBlock } from "./CitationsBlock";

const CITATIONS: Citation[] = [
  {
    source_type: "notion",
    title: "Código de Cultura",
    url: "",
    snippet: "Feedback direto e respeitoso.",
  },
  {
    source_type: "web",
    title: "Documentação externa",
    url: "https://example.com/doc",
    snippet: "Trecho externo.",
  },
];

describe("CitationsBlock", () => {
  it("começa recolhido: só o resumo aparece, nenhum título de fonte", () => {
    render(<CitationsBlock citations={CITATIONS} />);
    const toggle = screen.getByRole("button", { name: /2 fontes/i });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("Código de Cultura")).not.toBeInTheDocument();
    expect(screen.queryByText("Documentação externa")).not.toBeInTheDocument();
  });

  it("expande a lista ao clicar; cada fonte abre o trecho sob demanda", () => {
    render(<CitationsBlock citations={CITATIONS} />);
    fireEvent.click(screen.getByRole("button", { name: /2 fontes/i }));
    expect(screen.getByRole("button", { name: /2 fontes/i })).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("Código de Cultura")).toBeInTheDocument();
    // O trecho continua fechado até o clique na fonte.
    expect(screen.queryByText(/feedback direto/i)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /código de cultura/i }));
    expect(screen.getByText(/feedback direto/i)).toBeInTheDocument();
  });

  it("fonte web expandida expõe o link externo com alvo seguro", () => {
    render(<CitationsBlock citations={CITATIONS} />);
    fireEvent.click(screen.getByRole("button", { name: /2 fontes/i }));
    fireEvent.click(screen.getByRole("button", { name: /documentação externa/i }));
    const link = screen.getByRole("link", { name: /abrir fonte/i });
    expect(link).toHaveAttribute("href", "https://example.com/doc");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noreferrer");
  });

  it("usa singular quando há uma fonte só", () => {
    render(<CitationsBlock citations={[CITATIONS[0]]} />);
    expect(screen.getByRole("button", { name: /^1 fonte$/i })).toBeInTheDocument();
  });

  it("não renderiza nada sem fontes", () => {
    const { container } = render(<CitationsBlock citations={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
