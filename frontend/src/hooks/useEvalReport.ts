import { useCallback, useEffect, useState } from "react";
import type { EvalReportPayload } from "../lib/types.ops";
import { getEvalReport } from "../data/opsSource";

/** Nunca lança: falha vira estado `error`. */
export function useEvalReport() {
  const [payload, setPayload] = useState<EvalReportPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setPayload(await getEvalReport());
    } catch (e) {
      setPayload(null);
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return { payload, error, refresh, loading };
}
