import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";

const api = vi.hoisted(() => ({
  createCashRegister: vi.fn(),
  deleteCashRegister: vi.fn(),
  getCashRegisters: vi.fn(),
  getCashRegistersExportUrl: vi.fn(),
  pollAllCashRegisters: vi.fn(),
  pollCashRegister: vi.fn(),
  updateCashRegister: vi.fn(),
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

import CashRegistersPage from "./CashRegistersPage";

describe("CashRegistersPage", () => {
  it("runs poll-all from toolbar", async () => {
    api.getCashRegisters.mockResolvedValue({
      data: [
        {
          id: "k-1",
          kkm_number: "1001",
          store_number: "12",
          store_code: "0012",
          serial_number: "SN-1001",
          inventory_number: "INV-1001",
          terminal_id_rs: null,
          terminal_id_sber: null,
          windows_version: "10",
          kkm_type: "retail",
          cash_number: "1",
          hostname: "cash-01",
          comment: null,
          is_online: true,
          reachability_reason: null,
          last_polled_at: null,
          created_at: "2026-05-22T00:00:00Z",
        },
      ],
      count: 1,
    });
    api.getCashRegistersExportUrl.mockReturnValue("/api/v1/cash-registers/export.csv");
    api.pollAllCashRegisters.mockResolvedValue({ ok: true });

    const queryClient = new QueryClient();
    render(
      <QueryClientProvider client={queryClient}>
        <CashRegistersPage />
      </QueryClientProvider>,
    );

    expect(await screen.findByText("ККМ №1001")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Опросить все" }));
    await waitFor(() => expect(api.pollAllCashRegisters).toHaveBeenCalledTimes(1));
  });

  it("filters list by offline status", async () => {
    api.getCashRegisters.mockResolvedValue({
      data: [
        {
          id: "k-1",
          kkm_number: "1001",
          store_number: "12",
          store_code: "0012",
          serial_number: "SN-1001",
          inventory_number: "INV-1001",
          terminal_id_rs: null,
          terminal_id_sber: null,
          windows_version: "10",
          kkm_type: "retail",
          cash_number: "1",
          hostname: "cash-online",
          comment: null,
          is_online: true,
          reachability_reason: null,
          last_polled_at: null,
          created_at: "2026-05-22T00:00:00Z",
        },
        {
          id: "k-2",
          kkm_number: "2002",
          store_number: "13",
          store_code: "0013",
          serial_number: "SN-2002",
          inventory_number: "INV-2002",
          terminal_id_rs: null,
          terminal_id_sber: null,
          windows_version: "11",
          kkm_type: "shtrih",
          cash_number: "2",
          hostname: "cash-offline",
          comment: null,
          is_online: false,
          reachability_reason: "host_unreachable",
          last_polled_at: null,
          created_at: "2026-05-22T00:00:00Z",
        },
      ],
      count: 2,
    });
    api.getCashRegistersExportUrl.mockReturnValue("/api/v1/cash-registers/export.csv");

    const queryClient = new QueryClient();
    render(
      <QueryClientProvider client={queryClient}>
        <CashRegistersPage />
      </QueryClientProvider>,
    );

    expect(await screen.findByText("ККМ №1001")).toBeInTheDocument();
    expect(screen.getByText("ККМ №2002")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Оффлайн/i }));

    expect(screen.queryByText("ККМ №1001")).not.toBeInTheDocument();
    expect(screen.getByText("ККМ №2002")).toBeInTheDocument();
  });
});
