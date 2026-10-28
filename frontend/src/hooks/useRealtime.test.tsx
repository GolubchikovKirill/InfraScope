import { renderHook } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { vi } from "vitest";

import { INVALIDATE_COALESCE_MS, useRealtime } from "./useRealtime";

class FakeSocket {
  static last: FakeSocket | null = null;
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: ((event: { code: number }) => void) | null = null;
  onerror: (() => void) | null = null;
  constructor() {
    FakeSocket.last = this;
  }
  close() {}
  emit(payload: object) {
    this.onmessage?.({ data: JSON.stringify(payload) });
  }
}

describe("useRealtime", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.stubGlobal("WebSocket", FakeSocket);
    localStorage.setItem("access_token", "token");
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it("turns a burst of invalidations into one refetch per list", async () => {
    const client = new QueryClient();
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
    renderHook(() => useRealtime(), { wrapper });
    await vi.waitFor(() => expect(FakeSocket.last).not.toBeNull());

    const socket = FakeSocket.last!;
    for (let i = 0; i < 5; i += 1) socket.emit({ event: "invalidate", id: "printers" });
    socket.emit({ event: "invalidate", id: "switches" });
    socket.emit({ event: "invalidate", id: "switch_ports:abc" }); // per-switch namespace, no list for it
    expect(invalidate).not.toHaveBeenCalled();

    vi.advanceTimersByTime(INVALIDATE_COALESCE_MS);

    const keys = invalidate.mock.calls.map(([filters]) => filters?.queryKey?.[0]);
    expect(keys.sort()).toEqual(["printers", "switch-ports", "switches"]);
  });
});
