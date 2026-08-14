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
        isSuperuser
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
        selectedId="stock-1"
        isSuperuser
        onSelect={vi.fn()}
        onAdjust={vi.fn()}
        onIssue={vi.fn()}
      />,
    );

    expect(screen.getByText(/issued to Store A/i)).toBeInTheDocument();
  });

  it("sorts rows by column when a header is clicked, toggling direction on repeat clicks", () => {
    const multiRows: CartridgeStock[] = [
      { ...rows[0], id: "a", cartridge_name: "W2300A", quantity_on_hand: 10 },
      { ...rows[0], id: "b", cartridge_name: "CF210A", quantity_on_hand: 2 },
      { ...rows[0], id: "c", cartridge_name: "CE320A", quantity_on_hand: 6 },
    ];

    render(
      <CartridgeStockPanel
        rows={multiRows}
        movements={[]}
        loading={false}
        isSuperuser
        onSelect={vi.fn()}
        onAdjust={vi.fn()}
        onIssue={vi.fn()}
      />,
    );

    const namesInOrder = () => screen.getAllByRole("row").slice(1).map((row) => row.textContent);

    // Default order is by name ascending, as the server already returns it.
    expect(namesInOrder()[0]).toContain("CE320A");

    fireEvent.click(screen.getByRole("button", { name: "Остаток" }));
    expect(namesInOrder()[0]).toContain("CF210A"); // quantity 2, lowest first (asc)

    fireEvent.click(screen.getByRole("button", { name: "Остаток" }));
    expect(namesInOrder()[0]).toContain("W2300A"); // same column again -> desc, highest first
  });
});
