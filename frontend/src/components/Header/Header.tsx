import { Link } from "react-router-dom";
import { Logo } from "../Logo/Logo";
import { ThemeToggle } from "../ThemeToggle/ThemeToggle";
import styles from "./Header.module.css";

/**
 * Sobrou para a página de ops. O produto não tem mais navegação: a raiz é o
 * chat, e /ops é alcançável só por quem digita a URL.
 */
export function Header() {
  return (
    <header className={styles.header}>
      <div className={`container ${styles.inner}`}>
        <Link to="/" className={styles.brand}>
          <Logo size={40} />
          <span className={styles.brandText}>Oracle <span className="text-gradient">Borderless</span></span>
        </Link>
        <nav className={styles.nav}>
          <ThemeToggle />
        </nav>
      </div>
    </header>
  );
}
