import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { EmptyState } from "./EmptyState";

describe("EmptyState", () => {
  it("não expõe o gatilho de erro de demonstração", () => {
    render(<EmptyState onPick={vi.fn()} />);
    expect(screen.queryByText(/estado de erro/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/\[demo-error\]/)).not.toBeInTheDocument();
  });

  it("manda a pergunta do card clicado", () => {
    const onPick = vi.fn();
    render(<EmptyState onPick={onPick} />);

    const [first] = screen.getAllByRole("button");
    fireEvent.click(first);

    expect(onPick).toHaveBeenCalledTimes(1);
    expect(onPick.mock.calls[0][0]).toEqual(expect.any(String));
    expect(onPick.mock.calls[0][0]).not.toContain("demo");
  });
});
