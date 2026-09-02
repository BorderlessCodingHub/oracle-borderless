import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { EmptyState } from "./EmptyState";

describe("EmptyState", () => {
  it("não expõe o gatilho de erro de demonstração", () => {
    render(<EmptyState onPick={vi.fn()} />);
    // Legítima: "estado de erro" era o e.text do card DEMO, de fato renderizado
    // num <span>. Some se o card sumir.
    expect(screen.queryByText(/estado de erro/i)).not.toBeInTheDocument();
    // Mais forte que checar o texto do card de demo isoladamente: trava o
    // total em 4, então um quinto card (de demo ou qualquer outro) reintroduzido
    // no array EXAMPLES quebra este teste mesmo que o texto mude.
    expect(screen.getAllByRole("button")).toHaveLength(4);
  });

  it("manda a pergunta do card clicado", () => {
    const onPick = vi.fn();
    render(<EmptyState onPick={onPick} />);

    const [first] = screen.getAllByRole("button");
    fireEvent.click(first);

    // Falha se o onClick não chamar onPick, chamar mais de uma vez, ou passar
    // algo diferente do texto da pergunta do primeiro card (ex.: a tag, ou um
    // sentinel escondido em vez do texto visível).
    expect(onPick).toHaveBeenCalledTimes(1);
    expect(onPick).toHaveBeenCalledWith("Como funciona o Web3 Global Developer?");
  });
});
