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
  status: null,
  toner_black: 12,
  toner_cyan: 60,
  toner_magenta: 70,
  toner_yellow: 80,
  toner_black_name: "CF259A",
  toner_cyan_name: "W2031A",
  toner_magenta_name: "W2033A",
  toner_yellow_name: "W2032A",
  last_polled_at: null,
  created_at: "2026-05-21T00:00:00Z",
};

describe("PrinterCard", () => {
  beforeEach(() => {
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
});
