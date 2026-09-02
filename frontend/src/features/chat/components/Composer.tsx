import { useState } from "react";
import styles from "../ChatPage.module.css";

export function Composer({ onSend, disabled }: { onSend: (q: string) => void; disabled?: boolean }) {
  const [value, setValue] = useState("");
  function submit(e: React.FormEvent) {
    e.preventDefault();
    const q = value.trim();
    if (!q || disabled) return;
    onSend(q);
    setValue("");
  }
  return (
    <form className={styles.composer} onSubmit={submit}>
      <input
        name="question"
        aria-label="Pergunta ao oráculo"
        autoComplete="off"
        enterKeyHint="send"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder="Faça sua pergunta…"
      />
      <button type="submit" aria-label="Enviar" disabled={disabled}>↑</button>
    </form>
  );
}
