import { Link } from "react-router-dom";
import { Logo } from "../Logo/Logo";
import { Button } from "../Button/Button";
import { ThemeToggle } from "../ThemeToggle/ThemeToggle";
import { useCurrentUser } from "../../hooks/useCurrentUser";
import styles from "./Header.module.css";

export function Header() {
  const { isAdmin } = useCurrentUser();
  return (
    <header className={styles.header}>
      <div className={`container ${styles.inner}`}>
        <Link to="/" className={styles.brand}>
          <Logo size={40} />
          <span className={styles.brandText}>Oracle <span className="text-gradient">Borderless</span></span>
        </Link>
        <nav className={styles.nav}>
          <Link to="/about">Sobre &amp; Fontes</Link>
          <Link to="/knowledge">Base de conhecimento</Link>
          {isAdmin && <Link to="/ops">Ops</Link>}
          <ThemeToggle />
          <Button variant="gradient" to="/oracle">Abrir o oráculo →</Button>
        </nav>
      </div>
    </header>
  );
}
