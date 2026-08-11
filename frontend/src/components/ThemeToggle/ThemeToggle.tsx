import { useTheme } from "../../hooks/useTheme";
import type { Theme } from "../../lib/theme";
import styles from "./ThemeToggle.module.css";

// Selector U+FE0E força apresentação de texto (monocromática) em vez de
// emoji colorido — sem ele, "☀" vira um sol colorido no iOS/Android e "☾"
// falta em várias fontes fallback do Windows.
const OPTIONS: { value: Theme; label: string; icon: string; title: string }[] = [
  { value: "system", label: "Sistema", icon: "◐︎", title: "Seguir o tema do sistema" },
  { value: "light", label: "Claro", icon: "☀︎", title: "Tema claro" },
  { value: "dark", label: "Escuro", icon: "☾︎", title: "Tema escuro" },
];

export function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  return (
    <div className={styles.group} role="group" aria-label="Tema da interface">
      {OPTIONS.map((option) => (
        <button
          key={option.value}
          type="button"
          aria-pressed={theme === option.value}
          title={option.title}
          className={theme === option.value ? styles.active : styles.option}
          onClick={() => setTheme(option.value)}
        >
          <span aria-hidden="true" className={styles.icon}>{option.icon}</span>
          <span className={styles.label}>{option.label}</span>
        </button>
      ))}
    </div>
  );
}
