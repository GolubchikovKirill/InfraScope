import { act, render } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useEntityAutoPoll } from "./useEntityAutoPoll";

function Probe({
  poll,
  enabled = true,
  intervalMs = 1_000,
}: {
  poll: () => Promise<unknown>;
  enabled?: boolean;
  intervalMs?: number;
}) {
  useEntityAutoPoll({
    enabled,
    queryKeyRoot: "computers",
    poll,
    intervalMs,
  });
  return null;
}

describe("useEntityAutoPoll", () => {
  afterEach(() => {
    vi.useRealTimers();
    Object.defineProperty(document, "hidden", {
      configurable: true,
      value: false,
    });
  });

  it("runs page-scoped polling and invalidates matching query root", async () => {
    vi.useFakeTimers();
    Object.defineProperty(document, "hidden", {
      configurable: true,
      value: false,
    });
    const poll = vi.fn().mockResolvedValue(undefined);
    const queryClient = new QueryClient();
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    render(
      <QueryClientProvider client={queryClient}>
        <Probe poll={poll} />
      </QueryClientProvider>,
    );

    await act(async () => {
      vi.advanceTimersByTime(1_000);
      await Promise.resolve();
    });

    expect(poll).toHaveBeenCalledTimes(1);
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ["computers"] });
  });

  it("does not poll while document is hidden", async () => {
    vi.useFakeTimers();
    Object.defineProperty(document, "hidden", {
      configurable: true,
      value: true,
    });
    const poll = vi.fn().mockResolvedValue(undefined);
    const queryClient = new QueryClient();

    render(
      <QueryClientProvider client={queryClient}>
        <Probe poll={poll} />
      </QueryClientProvider>,
    );

    await act(async () => {
      vi.advanceTimersByTime(2_000);
      await Promise.resolve();
    });

    expect(poll).not.toHaveBeenCalled();
  });
});
