import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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

describe("CartridgeStockPanel card editing", () => {
  it("opens a card for an existing row and saves every editable field", async () => {
    const onSaveCard = vi.fn().mockResolvedValue(undefined);

    render(
      <CartridgeStockPanel
        rows={rows}
        movements={[]}
        loading={false}
        isSuperuser
        onSelect={vi.fn()}
        onAdjust={vi.fn()}
        onIssue={vi.fn()}
        onSaveCard={onSaveCard}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /Карточка картриджа/i }));

    fireEvent.change(screen.getByLabelText(/Название \/ артикул/i), {
      target: { value: "Hi-Black · BCR-CC530A [K]" },
    });
    fireEvent.change(screen.getByLabelText("Цвет"), { target: { value: "magenta" } });
    fireEvent.change(screen.getByLabelText(/Совместимые принтеры/i), {
      target: { value: "HP CM2320, CP2025" },
    });
    fireEvent.change(screen.getByLabelText(/Минимум/i), { target: { value: "4" } });
    fireEvent.click(screen.getByRole("button", { name: /^Сохранить$/i }));

    await waitFor(() => expect(onSaveCard).toHaveBeenCalled());
    expect(onSaveCard).toHaveBeenCalledWith("stock-1", {
      cartridge_name: "Hi-Black · BCR-CC530A [K]",
      toner_color: "magenta",
      compatible_printer_models: "HP CM2320, CP2025",
      quantity_on_hand: 3,
      minimum_stock: 4,
      is_active: true,
      note: undefined,
    });
  });

  it("asks for a reason only when the quantity actually changes", () => {
    render(
      <CartridgeStockPanel
        rows={rows}
        movements={[]}
        loading={false}
        isSuperuser
        onSelect={vi.fn()}
        onAdjust={vi.fn()}
        onIssue={vi.fn()}
        onSaveCard={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /Карточка картриджа/i }));
    expect(screen.queryByLabelText(/Причина изменения остатка/i)).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText(/Остаток, шт/i), { target: { value: "9" } });
    expect(screen.getByLabelText(/Причина изменения остатка/i)).toBeInTheDocument();
  });

  it("creates a new card with null id and keeps archived rows out of the way", async () => {
    const onSaveCard = vi.fn().mockResolvedValue(undefined);
    const archivedRow: CartridgeStock = { ...rows[0], id: "arch", cartridge_name: "OLD-1", is_active: false };

    render(
      <CartridgeStockPanel
        rows={[rows[0], archivedRow]}
        movements={[]}
        loading={false}
        isSuperuser
        showArchived
        onSelect={vi.fn()}
        onAdjust={vi.fn()}
        onIssue={vi.fn()}
        onSaveCard={onSaveCard}
        onArchive={vi.fn()}
      />,
    );

    // The archived row is labelled and offers no second "to archive" action.
    expect(screen.getByText("в архиве")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /В архив/i })).toHaveLength(1);

    fireEvent.click(screen.getByRole("button", { name: /Добавить картридж/i }));
    fireEvent.change(screen.getByLabelText(/Название \/ артикул/i), { target: { value: "W2070A" } });
    fireEvent.click(screen.getByRole("button", { name: /^Сохранить$/i }));

    await waitFor(() =>
      expect(onSaveCard).toHaveBeenCalledWith(null, expect.objectContaining({ cartridge_name: "W2070A" })),
    );
  });

  it("hides editing controls from non-superusers", () => {
    render(
      <CartridgeStockPanel
        rows={rows}
        movements={[]}
        loading={false}
        isSuperuser={false}
        onSelect={vi.fn()}
        onAdjust={vi.fn()}
        onIssue={vi.fn()}
        onSaveCard={vi.fn()}
        onArchive={vi.fn()}
      />,
    );

    expect(screen.queryByRole("button", { name: /Добавить картридж/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Карточка картриджа/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /В архив/i })).not.toBeInTheDocument();
  });
});
