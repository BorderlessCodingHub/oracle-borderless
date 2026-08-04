import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ThemeProvider } from "../../hooks/useTheme";
import { stubMatchMedia } from "../../test/matchMedia";
import { ThemeToggle } from "./ThemeToggle";

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
});

function renderToggle() {
  return render(
    <ThemeProvider>
      <ThemeToggle />
    </ThemeProvider>
  );
}

describe("ThemeToggle", () => {
  it("expõe as três opções num radiogroup", () => {
    stubMatchMedia(true);
    renderToggle();
    expect(screen.getByRole("radiogroup", { name: "Tema da interface" })).toBeInTheDocument();
    expect(screen.getAllByRole("radio")).toHaveLength(3);
  });

  it("marca 'Sistema' quando não há preferência salva", () => {
    stubMatchMedia(true);
    renderToggle();
    expect(screen.getByRole("radio", { name: "Sistema" })).toBeChecked();
  });

  it("aplica o tema claro no <html> e persiste ao clicar em 'Claro'", () => {
    stubMatchMedia(true);
    renderToggle();
    fireEvent.click(screen.getByRole("radio", { name: "Claro" }));
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
    expect(screen.getByRole("radio", { name: "Claro" })).toBeChecked();
    expect(screen.getByRole("radio", { name: "Sistema" })).not.toBeChecked();
    expect(localStorage.getItem("ob-theme")).toBe("light");
  });

  it("volta para escuro ao clicar em 'Escuro'", () => {
    stubMatchMedia(false);
    renderToggle();
    fireEvent.click(screen.getByRole("radio", { name: "Escuro" }));
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    expect(localStorage.getItem("ob-theme")).toBe("dark");
  });
});
