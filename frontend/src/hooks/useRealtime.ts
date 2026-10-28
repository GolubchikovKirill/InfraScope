import { useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import api from "../api/http";

/** Server cache namespace -> the React Query keys that show it. */
const ENTITY_QUERY_KEYS: Record<string, string[]> = {
  printers: ["printers"],
  media_players: ["media-players"],
  switches: ["switches", "switch-ports"],
  cash_registers: ["cash-registers"],
  computers: ["computers"],
};

/**
 * Invalidations arrive in bursts: a poll cycle, a bulk edit or a reboot run
 * announce the same entity several times within a second, and every tab
 * refetched the whole list once per message. Collecting them for a short
 * window turns a burst into one refetch per list.
 */
export const INVALIDATE_COALESCE_MS = 400;

export function useRealtime() {
  const queryClient = useQueryClient();
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    let reconnectTimeout: number;
    let attempts = 0;
    let disposed = false;
    const pending = new Set<string>();
    let flushTimeout: number | undefined;

    function flush() {
      flushTimeout = undefined;
      for (const entity of pending) {
        for (const key of ENTITY_QUERY_KEYS[entity] ?? []) {
          queryClient.invalidateQueries({ queryKey: [key] });
        }
      }
      pending.clear();
    }

    function scheduleInvalidate(entity: string) {
      if (!(entity in ENTITY_QUERY_KEYS)) return;
      pending.add(entity);
      flushTimeout ??= window.setTimeout(flush, INVALIDATE_COALESCE_MS);
    }

    // 3s, 6s, 12s, 24s, then hold at 30s - a socket that never opens (stale
    // token, backend down) must not hammer the handshake once per 3s forever.
    const backoffMs = () => Math.min(30_000, 3_000 * 2 ** Math.min(attempts, 4));

    async function connect() {
      if (disposed) return;

      const token = localStorage.getItem("access_token");
      if (!token) {
        // Not logged in yet - retry once auth completes rather than
        // connecting unauthenticated and getting closed immediately.
        reconnectTimeout = window.setTimeout(connect, 3000);
        return;
      }

      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      const host = window.location.host;
      const wsUrl = `${protocol}//${host}/api/v1/realtime/ws?token=${encodeURIComponent(token)}`;

      let opened = false;
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        opened = true;
        attempts = 0;
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.event === "invalidate" && typeof data.id === "string") scheduleInvalidate(data.id);
        } catch {
          // ignore parse errors
        }
      };

      ws.onclose = async (event) => {
        wsRef.current = null;
        if (disposed) return;
        attempts += 1;

        // Never handshaked, or closed with the unauthorized code: the token
        // in localStorage is stale. One authenticated HTTP call goes through
        // the axios interceptor, which transparently refreshes the token
        // (or redirects to /login if the session is truly dead); the next
        // reconnect then picks up the fresh token. Without this the socket
        // would retry with the same dead token indefinitely.
        if (!opened || event.code === 4401) {
          try {
            await api.get("/auth/me");
          } catch {
            // interceptor already handled the refresh failure
          }
        }

        reconnectTimeout = window.setTimeout(connect, opened ? 3000 : backoffMs());
      };

      ws.onerror = () => {
        ws.close();
      };
    }

    connect();

    return () => {
      disposed = true;
      clearTimeout(reconnectTimeout);
      clearTimeout(flushTimeout);
      if (wsRef.current) {
        wsRef.current.onclose = null; // Prevent reconnect loop on unmount
        wsRef.current.close();
      }
    };
  }, [queryClient]);
}
