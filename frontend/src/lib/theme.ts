export type Theme = "system" | "light" | "dark";
export type ResolvedTheme = "light" | "dark";

/** Duplicada no script inline de index.html — mudou aqui, mude lá. */
export const THEME_STORAGE_KEY = "ob-theme";

const THEMES: readonly string[] = ["system", "light", "dark"];

export function readStoredTheme(): Theme {
  try {
    const raw = localStorage.getItem(THEME_STORAGE_KEY);
    return raw !== null && THEMES.includes(raw) ? (raw as Theme) : "system";
  } catch {
    return "system";
  }
}

export function storeTheme(theme: Theme): void {
  try {
    localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    // Storage bloqueado (modo privado): o tema vale só para esta sessão.
  }
}

export function resolveTheme(theme: Theme): ResolvedTheme {
  if (theme === "light" || theme === "dark") return theme;
  if (typeof matchMedia !== "function") return "dark";
  return matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function applyTheme(theme: Theme): ResolvedTheme {
  const resolved = resolveTheme(theme);
  document.documentElement.setAttribute("data-theme", resolved);
  return resolved;
}
