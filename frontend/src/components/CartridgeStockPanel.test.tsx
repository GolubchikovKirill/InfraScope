import { fireEvent, render, screen } from "@testing-library/react";
import { vi } from "vitest";

import type { CartridgeStock, CartridgeStockMovement } from "../client";
import CartridgeStockPanel from "./CartridgeStockPanel";

const rows: CartridgeStock[] = [
  {
    id: "stock-1",
    cartridge_name: "CF259A",
    toner_color: "black",
    compatible_printer_models: "HP M404",
    printer_count: 2,
    quantity_on_hand: 3,
    minimum_stock: 1,
    is_active: true,
    last_synced_at: "2026-05-22T00:00:00Z",
    created_at: "2026-05-22T00:00:00Z",
    updated_at: null,
  },
];

const movements: CartridgeStockMovement[] = [
  {
    id: "move-1",
    stock_id: "stock-1",
    delta: -1,
    reason: "issue",
    note: "issued to Store A",
    created_by: "admin@example.com",
    created_at: "2026-05-22T01:00:00Z",
  },
];

describe("CartridgeStockPanel", () => {
  it("adjusts stock and issues one cartridge", () => {
    const onAdjust = vi.fn();
    const onIssue = vi.fn();

    render(
      <CartridgeStockPanel
        rows={rows}
        movements={[]}
        loading={false}
        syncing={false}
        isSuperuser
        onSync={vi.fn()}
        onSelect={vi.fn()}
        onAdjust={onAdjust}
        onIssue={onIssue}
      />,
    );

    fireEvent.change(screen.getAllByDisplayValue("3")[0], { target: { value: "5" } });
    fireEvent.click(screen.getByRole("button", { name: /Сохранить остаток/i }));
    fireEvent.click(screen.getByRole("button", { name: /Выдать 1 картридж/i }));

    expect(onAdjust).toHaveBeenCalledWith("stock-1", 5, 1);
    expect(onIssue).toHaveBeenCalledWith("stock-1");
  });

  it("shows movement history for selected item", () => {
    render(
      <CartridgeStockPanel
        rows={rows}
        movements={movements}
        loading={false}
        syncing={false}
        selectedId="stock-1"
        isSuperuser
        onSync={vi.fn()}
        onSelect={vi.fn()}
        onAdjust={vi.fn()}
        onIssue={vi.fn()}
      />,
    );

    expect(screen.getByText(/issued to Store A/i)).toBeInTheDocument();
  });
});
