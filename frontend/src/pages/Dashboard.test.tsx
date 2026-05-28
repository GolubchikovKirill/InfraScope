import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";

const api = vi.hoisted(() => ({
  getPrinters: vi.fn(),
  getCartridgeStocks: vi.fn(),
  getCartridgeStockMovements: vi.fn(),
  getOfflineRiskPredictions: vi.fn(),
  issueCartridgeStock: vi.fn(),
  pollAllPrinters: vi.fn(),
  pollPrinter: vi.fn(),
  createPrinter: vi.fn(),
  syncCartridgeStocks: vi.fn(),
  updatePrinter: vi.fn(),
  updateCartridgeStock: vi.fn(),
  deletePrinter: vi.fn(),
  getTonerPredictions: vi.fn(),
}));

vi.mock("../auth", () => ({
  useAuth: () => ({
    user: { is_superuser: true },
  }),
}));

vi.mock("../hooks/useEntityAutoPoll", () => ({
  useEntityAutoPoll: () => undefined,
}));

vi.mock("../hooks/useDebouncedValue", () => ({
  useDebouncedValue: (value: string) => value,
}));

vi.mock("../client", () => api);

vi.mock("../components/PrinterCard", () => ({
  default: ({ printer }: { printer: { model: string } }) => <div>{printer.model}</div>,
}));

vi.mock("../components/ZebraCard", () => ({
  default: ({ printer }: { printer: { model: string } }) => <div>{printer.model}</div>,
}));

vi.mock("../components/PrinterForm", () => ({
  default: () => <div>PrinterForm</div>,
}));

vi.mock("../components/CartridgeStockPanel", () => ({
  default: () => <div>CartridgeStockPanel</div>,
}));

import Dashboard from "./Dashboard";

describe("Dashboard", () => {
  it("runs poll-all with active printer tab", async () => {
    api.getPrinters.mockResolvedValue({
      data: [
        {
          id: "p-1",
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
          toner_black: 40,
          toner_cyan: null,
          toner_magenta: null,
          toner_yellow: null,
          toner_black_name: null,
          toner_cyan_name: null,
          toner_magenta_name: null,
          toner_yellow_name: null,
          last_polled_at: null,
          created_at: "2026-05-22T00:00:00Z",
        },
      ],
      count: 1,
    });
    api.getTonerPredictions.mockResolvedValue({ data: [], count: 0 });
    api.getOfflineRiskPredictions.mockResolvedValue({ data: [], count: 0 });
    api.pollAllPrinters.mockResolvedValue({ ok: true });

    const queryClient = new QueryClient();
    render(
      <QueryClientProvider client={queryClient}>
        <Dashboard />
      </QueryClientProvider>,
    );

    expect(await screen.findByText("HP M404")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Опросить все" }));
    await waitFor(() => expect(api.pollAllPrinters).toHaveBeenCalledWith("laser"));

    fireEvent.click(screen.getByRole("button", { name: "Этикеточные" }));
    fireEvent.click(screen.getByRole("button", { name: "Опросить все" }));
    await waitFor(() => expect(api.pollAllPrinters).toHaveBeenCalledWith("label"));
  });
});
