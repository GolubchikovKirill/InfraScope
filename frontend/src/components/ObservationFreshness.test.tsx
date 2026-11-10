import { act, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import OnlineStatusBadge from "./OnlineStatusBadge";
import { parseApiTimestamp } from "../lib/apiTimestamp";

afterEach(() => vi.useRealTimers());

it("reads the API's offset-free database time as UTC", () => {
  expect(parseApiTimestamp("2026-11-10T08:14:50.816173")).toBe(Date.parse("2026-11-10T08:14:50.816Z"));
  expect(parseApiTimestamp("2026-11-10T11:14:50.816+03:00")).toBe(Date.parse("2026-11-10T08:14:50.816Z"));
  expect(parseApiTimestamp(null)).toBeNaN();
});

it("shows online for a recent offset-free UTC observation", () => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-11-10T08:15:00Z"));
  render(<OnlineStatusBadge isOnline={true} lastPolledAt="2026-11-10T08:14:50.816173" />);
  expect(screen.getByText("Онлайн")).toBeInTheDocument();
  expect(screen.queryByText("Данные устарели")).not.toBeInTheDocument();
});

it("expires an observation while the page remains open", () => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-11-10T10:00:00Z"));
  render(<OnlineStatusBadge isOnline={true} lastPolledAt="2026-11-10T10:00:00Z" />);
  expect(screen.getByText("Онлайн")).toBeInTheDocument();
  act(() => vi.advanceTimersByTime(31 * 60_000));
  expect(screen.getByText("Данные устарели")).toBeInTheDocument();
});
