import { useEffect, useState } from "react";
import { Header } from "../../components/Header/Header";
import { Footer } from "../../components/Footer/Footer";
import { useOpsOverview } from "../../hooks/useOpsOverview";
import { useOpsTurns } from "../../hooks/useOpsTurns";
import { useEvalReport } from "../../hooks/useEvalReport";
import { getTurn } from "../../data/opsSource";
import type { OpsWindow, TurnDetail as Detail } from "../../lib/types.ops";
import type { MapBox } from "./architectureMap";
import { ArchitectureMap } from "./components/ArchitectureMap";
import { BoxDetail } from "./components/BoxDetail";
import { EvalPanel } from "./components/EvalPanel";
import { TurnDetail } from "./components/TurnDetail";
import { TurnList } from "./components/TurnList";
import { WindowPicker } from "./components/WindowPicker";
import styles from "./OpsPage.module.css";

export default function OpsPage() {
  const [window, setWindow] = useState<OpsWindow>("24h");
  const [box, setBox] = useState<MapBox | null>(null);
  const [turnId, setTurnId] = useState<string | null>(null);
  const [turn, setTurn] = useState<Detail | null>(null);
  const [turnError, setTurnError] = useState<string | null>(null);

  const { overview, error: overviewError } = useOpsOverview(window);
  const { turns, error: turnsError } = useOpsTurns(window);
  const { payload: evalPayload, error: evalError } = useEvalReport();

  // A janela mudou: o turno selecionado pode nem estar mais na lista.
  useEffect(() => {
    setTurnId(null);
    setTurn(null);
    setTurnError(null);
  }, [window]);

  useEffect(() => {
    if (!turnId) return;
    let current = true;
    setTurnError(null);
    void getTurn(turnId)
      .then((d) => {
        if (current) setTurn(d);
      })
      .catch((e: unknown) => {
        if (!current) return;
        setTurn(null);
        setTurnError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      current = false;
    };
  }, [turnId]);

  return (
    <>
      <Header />
      <main className="container">
        <p className="eyebrow">Ops</p>
        <div className={styles.head}>
          <h1 className={styles.title}>Como o oráculo respondeu</h1>
          <WindowPicker value={window} onChange={setWindow} />
        </div>
        <p className={styles.note}>
          O caminho que cada pergunta percorre — da base de conhecimento até a resposta —
          e o que aconteceu em cada turno recente. Só leitura.
        </p>

        <section className={styles.section}>
          <h2 className={styles.sectionTitle}>Arquitetura viva</h2>
          {overviewError && (
            <p className={styles.error}>Não foi possível carregar os números: {overviewError}</p>
          )}
          <div className={styles.mapLayout}>
            <ArchitectureMap overview={overview} selected={box} onSelect={setBox} />
            <BoxDetail box={box} />
          </div>
        </section>

        <section className={styles.section}>
          <h2 className={styles.sectionTitle}>Turnos recentes</h2>
          {turnsError && (
            <p className={styles.error}>Não foi possível carregar os turnos: {turnsError}</p>
          )}
          <div className={styles.turnLayout}>
            <TurnList turns={turns} selectedId={turnId} onSelect={setTurnId} />
            <div className={styles.detail}>
              {turnError ? (
                <p className={styles.error}>Não foi possível abrir o turno: {turnError}</p>
              ) : (
                <TurnDetail turn={turn} />
              )}
            </div>
          </div>
        </section>

        <section className={styles.section}>
          <h2 className={styles.sectionTitle}>Qualidade (eval)</h2>
          {evalError && (
            <p className={styles.error}>Não foi possível ler o report: {evalError}</p>
          )}
          <EvalPanel payload={evalPayload} />
        </section>
      </main>
      <Footer />
    </>
  );
}
