import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import type { ResolvedTheme, Theme } from "../lib/theme";
import { applyTheme, readStoredTheme, resolveTheme, storeTheme } from "../lib/theme";

type ThemeContextValue = {
  theme: Theme;
  resolved: ResolvedTheme;
  setTheme: (theme: Theme) => void;
};

const ThemeContext = createContext<ThemeContextValue | null>(null);

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<Theme>(readStoredTheme);
  const [resolved, setResolved] = useState<ResolvedTheme>(() => resolveTheme(theme));

  useEffect(() => {
    setResolved(applyTheme(theme));
  }, [theme]);

  // Em "system", acompanhar o SO ao vivo — sem reload.
  useEffect(() => {
    if (theme !== "system" || typeof matchMedia !== "function") return;
    const query = matchMedia("(prefers-color-scheme: dark)");
    const sync = () => setResolved(applyTheme("system"));
    query.addEventListener("change", sync);
    return () => query.removeEventListener("change", sync);
  }, [theme]);

  const setTheme = useCallback((next: Theme) => {
    setThemeState(next);
    storeTheme(next);
  }, []);

  const value = useMemo(() => ({ theme, resolved, setTheme }), [theme, resolved, setTheme]);
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeContextValue {
  const context = useContext(ThemeContext);
  if (!context) throw new Error("useTheme precisa estar dentro de <ThemeProvider>");
  return context;
}
