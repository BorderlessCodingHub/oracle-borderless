import { useCallback, useEffect, useState } from "react";
import type { OpsWindow, TurnSummary } from "../lib/types.ops";
import { listTurns } from "../data/opsSource";

/** Nunca lança: falha vira estado `error`. */
export function useOpsTurns(window: OpsWindow, limit = 50) {
  const [turns, setTurns] = useState<TurnSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setTurns(await listTurns(window, limit));
    } catch (e) {
      setTurns([]);
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [window, limit]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return { turns, error, refresh, loading };
}
