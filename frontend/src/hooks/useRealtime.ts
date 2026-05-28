import { useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";

export function useRealtime() {
  const queryClient = useQueryClient();
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    let reconnectTimeout: number;

    function connect() {
      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      const host = window.location.host;
      const wsUrl = `${protocol}//${host}/api/v1/realtime/ws`;

      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.event === "invalidate") {
            const entity = data.id;
            if (entity === "printers") queryClient.invalidateQueries({ queryKey: ["printers"] });
            else if (entity === "media_players") queryClient.invalidateQueries({ queryKey: ["media-players"] });
            else if (entity === "switches") {
              queryClient.invalidateQueries({ queryKey: ["switches"] });
              queryClient.invalidateQueries({ queryKey: ["switch-ports"] });
            }
            else if (entity === "cash_registers") queryClient.invalidateQueries({ queryKey: ["cash-registers"] });
            else if (entity === "computers") queryClient.invalidateQueries({ queryKey: ["computers"] });
          }
        } catch (err) {
          // ignore parse errors
        }
      };

      ws.onclose = () => {
        reconnectTimeout = window.setTimeout(connect, 3000);
      };

      ws.onerror = () => {
        ws.close();
      };
    }

    connect();

    return () => {
      clearTimeout(reconnectTimeout);
      if (wsRef.current) {
        wsRef.current.onclose = null; // Prevent reconnect loop on unmount
        wsRef.current.close();
      }
    };
  }, [queryClient]);
}
