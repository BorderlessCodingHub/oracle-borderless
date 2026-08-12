import { Logo } from "../../../components/Logo/Logo";
import styles from "../ChatPage.module.css";

// Perguntas dos roots que a base realmente cobre. Exemplo fora do escopo cai na
// recusa padrão e ensina a pessoa errado logo no primeiro contato.
const EXAMPLES = [
  { tag: "PRODUTOS", text: "Como funciona o Web3 Global Developer?" },
  { tag: "CULTURA", text: "O que diz o Código de Cultura sobre feedback?" },
  { tag: "PAPÉIS", text: "Quais são os papéis do Mapa Global?" },
  { tag: "DOMÍNIOS", text: "Quais domínios e subdomínios existem no ecossistema?" },
];

export function EmptyState({ onPick }: { onPick: (q: string) => void }) {
  return (
    <div className={styles.empty}>
      <Logo size={72} />
      <h2>Olá! Pergunte qualquer coisa.</h2>
      <p>Eu respondo sobre as regras e a operação do ecossistema — sempre com base nos documentos aprovados, e sempre citando as fontes.</p>
      <div className={styles.exampleGrid}>
        {EXAMPLES.map((e) => (
          <button key={e.tag} className={styles.exampleCard} onClick={() => onPick(e.text)}>
            <span className={styles.exampleTag}>{e.tag}</span>
            <span>{e.text}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
