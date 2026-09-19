import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
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
  getRemoteDevices: vi.fn(),
}));

vi.mock("../auth", () => ({ useAuth: () => ({ user: { email: "a@b.c", is_superuser: true } }) }));

vi.mock("../components/RemoteAccessButtons", () => ({
  default: ({ hostname }: { hostname: string }) => <button type="button">Подключиться к {hostname}</button>,
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
    api.getCashRegisters.mockResolvedValue({
      data: [
        { id: "cash-1", hostname: "VNA-KKM-201", store_number: "A2(200)", location_zone: "DF", kkm_number: "1", is_online: true, piot_status: "Обновлен", cash_drawer: "Да", terminal_status: null },
        { id: "cash-2", hostname: "VNA-KKM-202", store_number: "A2(200)", location_zone: "DF", kkm_number: "2", is_online: false, reachability_reason: "no_response", piot_status: null, cash_drawer: null, terminal_status: null },
      ],
      count: 2,
    });
    api.getRemoteDevices.mockResolvedValue({ data: [], count: 0 });
    api.getComputers.mockResolvedValue({
      data: [
        { id: "pc-1", hostname: "VNA-MGR-205", location: null, comment: null, is_online: true },
        { id: "pc-2", hostname: "VN3-MGR-001", location: null, comment: null, is_online: false, reachability_reason: "no_response" },
      ],
      count: 2,
    });
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

  it("puts the stock summary next to the general statistics, above the cash map", async () => {
    renderOverview();

    const stats = await screen.findByRole("region", { name: "Общая статистика" });
    expect(within(stats).getByText("Расходники")).toBeInTheDocument();
    expect(within(stats).getByText("Склад картриджей")).toBeInTheDocument();
    expect(within(stats).getByRole("link", { name: /Расходники/ })).toHaveAttribute("href", "/printers");

    const map = screen.getByRole("region", { name: "По магазинам" });
    expect(stats.compareDocumentPosition(map) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("shows the registers by store and opens a quick look with the connect button", async () => {
    renderOverview();

    const offline = await screen.findByRole("button", { name: /VNA-KKM-202, A2\(200\), недоступна/ });
    expect(screen.getByRole("button", { name: /VNA-KKM-201, A2\(200\), на связи/ })).toBeInTheDocument();
    expect(within(screen.getByTestId("store-DF:A2(200)")).getByText("1/2")).toBeInTheDocument();

    fireEvent.click(offline);

    const dialog = await screen.findByRole("dialog", { name: "Касса VNA-KKM-202" });
    expect(within(dialog).getByRole("button", { name: "Подключиться к VNA-KKM-202" })).toBeInTheDocument();
    expect(within(dialog).getByText("Нет ответа")).toBeInTheDocument();

    fireEvent.click(within(dialog).getByRole("button", { name: "Закрыть" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("does not repeat the cash registers among the category cards", async () => {
    renderOverview();

    await screen.findByRole("region", { name: "По магазинам" });
    const categories = screen.getByText("По категориям").closest("section") as HTMLElement;
    expect(within(categories).queryByText("Кассы")).not.toBeInTheDocument();
    expect(within(categories).getByText("Сеть")).toBeInTheDocument();
  });

  it("switches the same map to computers, placed by store, and opens their quick look", async () => {
    renderOverview();

    fireEvent.click(await screen.findByRole("tab", { name: /Компьютеры/ }));

    // VNA-MGR-205 is A2 by its name, and VN3 is Внуково 3
    expect(within(await screen.findByTestId("store-DF:A2")).getByText("A2(200)")).toBeInTheDocument();
    const vn3 = screen.getByRole("button", { name: /VN3-MGR-001, VN3 · Внуково 3, недоступен/ });

    fireEvent.click(vn3);

    const dialog = await screen.findByRole("dialog", { name: "Компьютер VN3-MGR-001" });
    expect(within(dialog).getByText("VN3 · Внуково 3")).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Подключиться к VN3-MGR-001" })).toBeInTheDocument();
  });
});
