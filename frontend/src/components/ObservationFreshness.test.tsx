import { act, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import OnlineStatusBadge from "./OnlineStatusBadge";

afterEach(() => vi.useRealTimers());

it("expires an observation while the page remains open", () => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-11-10T10:00:00Z"));
  render(<OnlineStatusBadge isOnline={true} lastPolledAt="2026-11-10T10:00:00Z" />);
  expect(screen.getByText("Онлайн")).toBeInTheDocument();
  act(() => vi.advanceTimersByTime(31 * 60_000));
  expect(screen.getByText("Данные устарели")).toBeInTheDocument();
});
