import { render, screen } from "@testing-library/react";

import CartridgeJournalPanel from "./CartridgeJournalPanel";

describe("CartridgeJournalPanel", () => {
  it("lists swaps with the outgoing cartridge's life and the per-model median", () => {
    render(
      <CartridgeJournalPanel
        loading={false}
        stats={[{ cartridge_name: "CF259A", toner_color: "black", replacements: 3, median_lifetime_days: 41.6, median_pages: 3150 }]}
        rows={[
          {
            id: "r1",
            printer_id: "p1",
            store_name: "ДФ Шереметьево D-12",
            printer_model: "HP M404",
            toner_color: "black",
            cartridge_name: "CF259A",
            level_before: 4,
            level_after: 99,
            page_count: 52345,
            previous_replaced_at: "2026-09-01T10:00:00Z",
            lifetime_days: 38.2,
            pages_printed: 3200,
            replaced_at: "2026-10-09T10:00:00Z",
          },
        ]}
      />,
    );

    expect(screen.getByText("ДФ Шереметьево D-12")).toBeInTheDocument();
    expect(screen.getByText("4% → 99%")).toBeInTheDocument();
    expect(screen.getByText("38 дн.")).toBeInTheDocument();
    expect(screen.getByText(/служит 42 дн\./)).toHaveTextContent("3 150 стр.");
  });

  it("says when there is nothing yet", () => {
    render(<CartridgeJournalPanel loading={false} stats={[]} rows={[]} />);

    expect(screen.getByText(/журнал начнёт заполняться/)).toBeInTheDocument();
  });
});
