import { useCallback, useEffect, useState } from "react";
import type { OpsOverview, OpsWindow } from "../lib/types.ops";
import { getOverview } from "../data/opsSource";

/** Nunca lança: falha de rede/HTTP vira estado `error`, e a página segue de pé. */
export function useOpsOverview(window: OpsWindow) {
  const [overview, setOverview] = useState<OpsOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setOverview(await getOverview(window));
    } catch (e) {
      setOverview(null);
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [window]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return { overview, error, refresh, loading };
}
