import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { BrowserRouter } from "react-router-dom";
import { vi } from "vitest";

const api = vi.hoisted(() => ({
  getCartridgeStocks: vi.fn(),
  getCashRegisters: vi.fn(),
  getComputers: vi.fn(),
  getEventLogs: vi.fn(),
  getMediaPlayers: vi.fn(),
  getPrinters: vi.fn(),
  getSwitches: vi.fn(),
}));

vi.mock("../client", () => api);

import OverviewPage from "./OverviewPage";

function renderOverview() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <BrowserRouter>
      <QueryClientProvider client={queryClient}>
        <OverviewPage />
      </QueryClientProvider>
    </BrowserRouter>,
  );
}

describe("OverviewPage", () => {
  beforeEach(() => {
    api.getPrinters.mockImplementation((_search: string | undefined, type: "laser" | "label") => Promise.resolve({
      data: type === "laser"
        ? [{ id: "p-1", is_online: true, toner_black: 10, toner_cyan: null, toner_magenta: null, toner_yellow: null }]
        : [{ id: "p-2", is_online: true, toner_black: null, toner_cyan: null, toner_magenta: null, toner_yellow: null }],
      count: 1,
    }));
    api.getSwitches.mockResolvedValue({ data: [{ id: "sw-1", is_online: false }], count: 1 });
    api.getCashRegisters.mockResolvedValue({ data: [{ id: "cash-1", is_online: true, piot_status: "Обновлен", cash_drawer: "Да", terminal_status: null }], count: 1 });
    api.getComputers.mockResolvedValue({ data: [{ id: "pc-1", is_online: true }], count: 1 });
    api.getMediaPlayers.mockResolvedValue({ data: [{ id: "media-1", is_online: true }], count: 1 });
    api.getCartridgeStocks.mockResolvedValue({ data: [{ id: "stock-1", quantity_on_hand: 1, minimum_stock: 2 }], count: 1 });
    api.getEventLogs.mockResolvedValue({ data: [{ id: "event-1", severity: "error", category: "polling", message: "Свитч A1 недоступен", device_name: "A1", created_at: "2026-08-14T10:00:00Z" }], count: 1 });
  });

  it("prioritizes current infrastructure issues and links to the relevant sections", async () => {
    renderOverview();

    expect(await screen.findByText("Недоступно: 1 свитч")).toBeInTheDocument();
    expect(screen.getByText("Здоровье инфраструктуры")).toBeInTheDocument();
    expect(screen.getByText("Низкий уровень тонера")).toBeInTheDocument();
    expect(screen.getByText("Нужно пополнить склад")).toBeInTheDocument();
    expect(screen.getByText("Свитч A1 недоступен")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /недоступно: 1 свитч/i })).toHaveAttribute("href", "/switches");
  });
});
