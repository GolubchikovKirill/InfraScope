import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";

const api = vi.hoisted(() => ({
  createCashRegister: vi.fn(),
  deleteCashRegister: vi.fn(),
  getCashRegisters: vi.fn(),
  getCashRegistersExportUrl: vi.fn(),
  getCredentials: vi.fn(),
  getHonestSignCashRegisters: vi.fn(),
  checkAllHonestSignTargets: vi.fn(),
  checkHonestSignTarget: vi.fn(),
  initializeHonestSignTarget: vi.fn(),
  updateHonestSignTargetIp: vi.fn(),
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

vi.mock("../hooks/useRemoteDeviceMap", () => ({
  useRemoteDeviceMap: () => ({ map: new Map(), isLoading: false, isError: false }),
}));

vi.mock("../components/RemoteAccessButtons", () => ({ default: () => null }));

vi.mock("../client", () => api);

import CashRegistersPage from "./CashRegistersPage";
import { ConfirmProvider } from "../components/ConfirmDialog";

function renderPage() {
  const queryClient = new QueryClient();
  return render(
    <MemoryRouter>
      <QueryClientProvider client={queryClient}>
        <ConfirmProvider>
          <CashRegistersPage />
        </ConfirmProvider>
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

function cash(id: string, kkm: string, hostname: string) {
  return {
    id,
    kkm_number: kkm,
    store_number: "12",
    store_code: "0012",
    serial_number: null,
    inventory_number: null,
    terminal_id_rs: null,
    terminal_id_sber: null,
    windows_version: "10",
    kkm_type: "retail",
    cash_number: "1",
    hostname,
    comment: null,
    is_online: true,
    reachability_reason: null,
    last_polled_at: null,
    created_at: "2026-05-22T00:00:00Z",
  };
}

function hsStatus(host: string, overrides: Record<string, unknown> = {}) {
  return {
    host,
    label: "A12",
    hostname: "VNK-KKM-1501",
    original_host: host,
    reachable: true,
    status: "ready",
    version: "2.5.1",
    ready: true,
    message: "",
    checked_at: new Date().toISOString(),
    state_since: new Date().toISOString(),
    consecutive_failures: 0,
    ...overrides,
  };
}

function honestSignLinks(data: unknown[], overrides: Record<string, unknown> = {}) {
  return {
    data,
    unmatched_targets: [],
    ambiguous_hostnames: [],
    status_configured: true,
    initialization_configured: true,
    auto_check_enabled: true,
    auto_check_interval_minutes: 15,
    ...overrides,
  };
}

function hsLink(cashId: string, host: string, status: unknown) {
  return {
    cash_register_id: cashId,
    target: { host, label: "A12", hostname: "VNK-KKM-1501", original_host: host },
    status,
  };
}

describe("CashRegistersPage Honest Sign", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.getCredentials.mockResolvedValue({ data: [], count: 0 });
    api.getCashRegistersExportUrl.mockReturnValue("/api/v1/cash-registers/export.csv");
    api.getCashRegisters.mockResolvedValue({
      data: [cash("k-1", "1501", "VNK-KKM-1501"), cash("k-2", "1502", "VNK-KKM-1502")],
      count: 2,
    });
  });

  it("shows the Honest Sign block only on the linked register and warns about unmatched targets", async () => {
    api.getHonestSignCashRegisters.mockResolvedValue(
      honestSignLinks([hsLink("k-1", "172.23.8.21", hsStatus("172.23.8.21"))], {
        unmatched_targets: [{ host: "172.23.8.30", label: "A12", hostname: null, original_host: "172.23.8.30" }],
      }),
    );
    renderPage();

    await screen.findByText("ККМ №1501");
    expect(await screen.findAllByTestId("honest-sign-panel")).toHaveLength(1);
    expect(screen.getByText("готов")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("1 целей без кассы в списке");
  });

  it("shows no Honest Sign UI when the integration is not configured", async () => {
    api.getHonestSignCashRegisters.mockResolvedValue(
      honestSignLinks([hsLink("k-1", "172.23.8.21", null)], { status_configured: false }),
    );
    renderPage();

    await screen.findByText("ККМ №1501");
    expect(screen.queryByTestId("honest-sign-panel")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Проверить Честный знак" })).not.toBeInTheDocument();
  });

  it("runs a live check for one register and shows the result", async () => {
    api.getHonestSignCashRegisters.mockResolvedValue(
      honestSignLinks([hsLink("k-1", "172.23.8.21", hsStatus("172.23.8.21", { ready: false, status: "not_initialized" }))]),
    );
    api.checkHonestSignTarget.mockResolvedValue(hsStatus("172.23.8.21"));
    renderPage();

    await screen.findByText("not_initialized");
    const panel = screen.getByTestId("honest-sign-panel");
    fireEvent.click(within(panel).getByRole("button", { name: "Проверить Честный знак" }));

    await waitFor(() => expect(api.checkHonestSignTarget).toHaveBeenCalledWith("172.23.8.21"));
    expect(await screen.findByText("готов")).toBeInTheDocument();
  });

  it("asks for confirmation before activating and never offers it for a ready module", async () => {
    api.getHonestSignCashRegisters.mockResolvedValue(
      honestSignLinks([
        hsLink("k-1", "172.23.8.21", hsStatus("172.23.8.21", { ready: false, status: "not_initialized" })),
        hsLink("k-2", "172.23.8.22", hsStatus("172.23.8.22")),
      ]),
    );
    api.initializeHonestSignTarget.mockResolvedValue({ result: "READY", message: "" });
    api.checkHonestSignTarget.mockResolvedValue(hsStatus("172.23.8.21"));
    renderPage();

    const panels = await screen.findAllByTestId("honest-sign-panel");
    expect(within(panels[1]).getByRole("button", { name: "Активировать" })).toBeDisabled();

    fireEvent.click(within(panels[0]).getByRole("button", { name: "Активировать" }));
    expect(api.initializeHonestSignTarget).not.toHaveBeenCalled();
    const confirmButtons = await screen.findAllByRole("button", { name: "Активировать" });
    fireEvent.click(confirmButtons[confirmButtons.length - 1]);

    await waitFor(() => expect(api.initializeHonestSignTarget).toHaveBeenCalledWith("172.23.8.21"));
    await waitFor(() => expect(api.checkHonestSignTarget).toHaveBeenCalledWith("172.23.8.21"));
  });

  it("marks a status the background check has not refreshed as stale", async () => {
    const old = new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString();
    api.getHonestSignCashRegisters.mockResolvedValue(
      honestSignLinks([hsLink("k-1", "172.23.8.21", hsStatus("172.23.8.21", { checked_at: old }))]),
    );
    renderPage();

    expect(await screen.findByText("данные устарели")).toBeInTheDocument();
  });

  it("filters registers whose Honest Sign module is not ready", async () => {
    api.getHonestSignCashRegisters.mockResolvedValue(
      honestSignLinks([
        hsLink("k-1", "172.23.8.21", hsStatus("172.23.8.21", { ready: false, reachable: false, status: "ERROR" })),
        hsLink("k-2", "172.23.8.22", hsStatus("172.23.8.22")),
      ]),
    );
    renderPage();

    await screen.findByText("ККМ №1502");
    fireEvent.change(screen.getByDisplayValue("Все состояния"), { target: { value: "hs_problem" } });

    expect(screen.getByText("ККМ №1501")).toBeInTheDocument();
    expect(screen.queryByText("ККМ №1502")).not.toBeInTheDocument();
  });
});

describe("CashRegistersPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.getCredentials.mockResolvedValue({ data: [], count: 0 });
    api.getHonestSignCashRegisters.mockResolvedValue(honestSignLinks([]));
  });

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

    renderPage();

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

    renderPage();

    expect(await screen.findByText("ККМ №1001")).toBeInTheDocument();
    expect(screen.getByText("ККМ №2002")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Оффлайн/i }));

    expect(screen.queryByText("ККМ №1001")).not.toBeInTheDocument();
    expect(screen.getByText("ККМ №2002")).toBeInTheDocument();
  });

  it("links a cash register to its stored credentials", async () => {
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
          hostname: "VNA-KKM-1506",
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
    api.getCredentials.mockResolvedValue({
      data: [{ id: "c-1", category: "cash_register", host: "VNA-KKM-1506" }],
      count: 1,
    });

    renderPage();

    await screen.findByText("ККМ №1001");
    const link = await screen.findByTitle("Пароли этой кассы (1)");
    expect(link).toHaveAttribute("href", "/credentials?q=VNA-KKM-1506");
  });
});
