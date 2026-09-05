import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MessageBubble } from "./MessageBubble";

describe("MessageBubble", () => {
  it("não renderiza o marcador [Fonte: …] no texto; a fonte fica só no bloco de fontes", () => {
    render(
      <MessageBubble
        role="assistant"
        content={"O PSP é o programa premium.\n\n[Fonte: Offer Architecture, PSP — https://app.notion.com/p/x]"}
        citations={[
          {
            source_type: "notion",
            title: "Offer Architecture, PSP",
            url: "https://app.notion.com/p/x",
            snippet: "…",
          },
        ]}
      />
    );
    expect(screen.getByText("O PSP é o programa premium.")).toBeInTheDocument();
    expect(screen.queryByText(/\[Fonte:/)).not.toBeInTheDocument();
    expect(screen.queryByText(/app\.notion\.com/)).not.toBeInTheDocument();
    // a proveniência continua a um clique
    expect(screen.getByRole("button", { name: /1 fonte/i })).toBeInTheDocument();
  });

  it("renders the turn timeline above the text while streaming, and not otherwise", () => {
    const activity = [{ kind: "step" as const, name: "answer", status: "running" as const }];
    const { rerender } = render(
      <MessageBubble role="assistant" content="parcial" streaming activity={activity} />
    );
    expect(screen.getByText("Respondendo")).toBeInTheDocument();

    rerender(<MessageBubble role="assistant" content="final" activity={activity} />);
    expect(screen.queryByText("Respondendo")).not.toBeInTheDocument();
  });

  it("does not blink a cursor on an empty streaming bubble", () => {
    const { container } = render(<MessageBubble role="assistant" content="" streaming activity={[]} />);
    expect(container.querySelector("[class*='cursor']")).toBeNull();
    expect(screen.getByRole("list", { name: "Andamento da resposta" })).toHaveAttribute("aria-busy", "true");
  });
});
