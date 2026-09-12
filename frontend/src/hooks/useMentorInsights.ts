import { useCallback, useEffect, useState } from "react";
import type { MentorInsights } from "../lib/types.ops";
import { getMentorInsights } from "../data/opsSource";

/** Nunca lança: falha de rede/HTTP vira estado `error`, e a página segue de pé. */
export function useMentorInsights(programSlug?: string, days = 30) {
  const [insights, setInsights] = useState<MentorInsights | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setInsights(await getMentorInsights(programSlug, days));
    } catch (e) {
      setInsights(null);
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [programSlug, days]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return { insights, error, refresh, loading };
}
