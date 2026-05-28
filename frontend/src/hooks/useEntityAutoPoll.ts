import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";

type UseEntityAutoPollParams = {
  enabled?: boolean;
  queryKeyRoot: string;
  poll: () => Promise<unknown>;
  intervalMs?: number;
};

const DEFAULT_INTERVAL_MS = 15 * 60_000;

export function useEntityAutoPoll({
  enabled = true,
  queryKeyRoot,
  poll,
  intervalMs = DEFAULT_INTERVAL_MS,
}: UseEntityAutoPollParams) {
  const queryClient = useQueryClient();

  useEffect(() => {
    if (!enabled) return;

    let disposed = false;
    let running = false;

    const invalidate = () => {
      void queryClient.invalidateQueries({ queryKey: [queryKeyRoot] });
    };

    const run = async () => {
      if (disposed || running || document.hidden) return;
      running = true;
      try {
        await poll();
      } catch {
        // Silent background refresh failures should not interrupt operators.
      } finally {
        running = false;
        if (!disposed) {
          invalidate();
        }
      }
    };

    const onVisibilityChange = () => {
      if (!document.hidden) {
        invalidate();
      }
    };

    const timer = window.setInterval(() => {
      void run();
    }, intervalMs);
    document.addEventListener("visibilitychange", onVisibilityChange);

    return () => {
      disposed = true;
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, [enabled, intervalMs, poll, queryClient, queryKeyRoot]);
}
