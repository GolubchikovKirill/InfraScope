import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";

import type { Printer } from "../client";
import PrinterCard from "./PrinterCard";

const printer: Printer = {
  id: "printer-1",
  printer_type: "laser",
  connection_type: "ip",
  store_name: "Store A",
  model: "HP M404",
  ip_address: "10.0.0.10",
  mac_address: null,
  mac_status: null,
  host_pc: null,
  is_online: true,
  reachability_reason: null,
  status: null,
  toner_black: 12,
  toner_cyan: 60,
  toner_magenta: 70,
  toner_yellow: 80,
  toner_black_name: "CF259A",
  toner_cyan_name: "W2031A",
  toner_magenta_name: "W2033A",
  toner_yellow_name: "W2032A",
  toner_updated_at: null,
  last_polled_at: null,
  offline_count_24h: 0,
  created_at: "2026-05-21T00:00:00Z",
};

describe("PrinterCard", () => {
  beforeEach(() => {
    vi.useRealTimers();
  });

  it("shows a fresh printer card when the API returns UTC without an offset", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-11-10T08:15:00Z"));
    render(<PrinterCard printer={{ ...printer,
      last_polled_at: "2026-11-10T08:14:50.816173",
      toner_updated_at: "2026-11-10T08:12:56.512215",
      toner_observed_at: {
        black: "2026-11-10T08:12:56.512215+00:00",
        cyan: "2026-11-10T08:12:56.512215+00:00",
        magenta: "2026-11-10T08:12:56.512215+00:00",
        yellow: "2026-11-10T08:12:56.512215+00:00",
      },
    }} onPoll={vi.fn()} onEdit={vi.fn()} onDelete={vi.fn()} isPolling={false} isSuperuser={false} />);
    expect(screen.getByText("Онлайн")).toBeInTheDocument();
    expect(screen.queryByText(/устарели|Нет свежих измерений/i)).not.toBeInTheDocument();
    vi.useRealTimers();
  });

  it("copies cartridge model from toner models list", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText },
      configurable: true,
    });
    const onCopyToner = vi.fn();

    render(
      <PrinterCard
        printer={printer}
        onPoll={vi.fn()}
        onEdit={vi.fn()}
        onDelete={vi.fn()}
        isPolling={false}
        isSuperuser={false}
        onCopyToner={onCopyToner}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /Модели картриджей/i }));
    fireEvent.click(screen.getByRole("button", { name: /K: CF259A/i }));

    await waitFor(() => expect(writeText).toHaveBeenCalledWith("CF259A"));
    expect(onCopyToner).toHaveBeenCalledWith("CF259A");
  });

  it("copies cartridge model from toner level bar", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText },
      configurable: true,
    });
    const onCopyToner = vi.fn();

    render(
      <PrinterCard
        printer={printer}
        onPoll={vi.fn()}
        onEdit={vi.fn()}
        onDelete={vi.fn()}
        isPolling={false}
        isSuperuser={false}
        onCopyToner={onCopyToner}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /K 12%/i }));

    await waitFor(() => expect(writeText).toHaveBeenCalledWith("CF259A"));
    expect(onCopyToner).toHaveBeenCalledWith("CF259A");
  });

  it("closes additional actions menu on outside click and Escape", async () => {
    render(
      <PrinterCard
        printer={printer}
        onPoll={vi.fn()}
        onEdit={vi.fn()}
        onDelete={vi.fn()}
        isPolling={false}
        isSuperuser={true}
      />,
    );

    fireEvent.click(screen.getByTitle("Дополнительные действия"));
    expect(screen.getByText("Редактировать")).toBeInTheDocument();

    fireEvent.pointerDown(document.body);
    await waitFor(() => {
      expect(screen.queryByText("Редактировать")).not.toBeInTheDocument();
    });

    fireEvent.click(screen.getByTitle("Дополнительные действия"));
    expect(screen.getByText("Редактировать")).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });

    await waitFor(() => {
      expect(screen.queryByText("Редактировать")).not.toBeInTheDocument();
    });
  });

  it("leads with the store, with the model as the secondary line", () => {
    render(
      <PrinterCard
        printer={printer}
        onPoll={vi.fn()}
        onEdit={vi.fn()}
        onDelete={vi.fn()}
        isPolling={false}
        isSuperuser={false}
      />,
    );

    const heading = screen.getByRole("heading");
    expect(heading).toHaveTextContent("Store A");
    expect(heading).toHaveClass("app-card-store");
    expect(screen.getByText("HP M404")).not.toBe(heading);
  });
});
