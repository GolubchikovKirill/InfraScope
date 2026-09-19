import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { vi } from "vitest";
import type { RemoteDevice } from "../client";

const api = vi.hoisted(() => ({ getRemoteDevices: vi.fn(), getCashRegisters: vi.fn() }));
vi.mock("../client", () => api);
vi.mock("../auth", () => ({ useAuth: () => ({ user: { is_superuser: true } }) }));
vi.mock("../components/RemoteAccessButtons", () => ({
  default: ({ hostname }: { hostname: string }) => <button type="button">Подключиться к {hostname}</button>,
}));

import ScreensPage from "./ScreensPage";

const dev = (hostname: string, over: Partial<RemoteDevice> = {}): RemoteDevice =>
  ({
    id: hostname,
    hostname,
    location: null,
    type_tag: hostname.split("-")[1]?.toUpperCase() ?? null,
    online: true,
    host_online: true,
    logged_in_user: "TV",
    last_seen_at: null,
    ...over,
  }) as RemoteDevice;

const renderPage = () =>
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <ScreensPage />
    </QueryClientProvider>,
  );

beforeEach(() => {
  vi.clearAllMocks();
  api.getRemoteDevices.mockResolvedValue({
    data: [
      dev("VNA-TV-401"),
      dev("VNA-TV-402", { online: false, host_online: false, last_seen_at: "2026-09-10T10:00:00Z" }),
      dev("VN3-TV-001", { online: false, host_online: true }),
      dev("VNA-MGR-205"), // not a screen
      dev("VNA-KKM-401"), // not a screen
    ],
    count: 5,
  });
  api.getCashRegisters.mockResolvedValue({
    data: [{ id: "k1", hostname: "VNA-KKM-401", store_number: "A4(202)", location_zone: "DF", kkm_number: "1", is_online: true, source_order: null }],
    count: 1,
  });
});

describe("ScreensPage", () => {
  it("lists only the TV machines, grouped by store, active ones first by default", async () => {
    renderPage();

    const a4 = await screen.findByTestId("store-DF:A4");
    expect(within(a4).getByText("A4(202)")).toBeInTheDocument();
    expect(within(a4).getByTestId("screen-VNA-TV-401")).toBeInTheDocument();
    expect(within(screen.getByTestId("store-stores:VN3")).getByText("VN3 · Внуково 3")).toBeInTheDocument();
    expect(screen.queryByTestId("screen-VNA-MGR-205")).not.toBeInTheDocument();
    expect(screen.queryByTestId("screen-VNA-KKM-401")).not.toBeInTheDocument();
  });

  it("hides the screens that are off unless asked, and says how many it hid", async () => {
    renderPage();
    await screen.findByTestId("screen-VNA-TV-401");

    expect(screen.queryByTestId("screen-VNA-TV-402")).not.toBeInTheDocument();
    expect(screen.getByText("(скрыто 1)")).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText(/Только активные/));

    expect(await screen.findByTestId("screen-VNA-TV-402")).toBeInTheDocument();
    expect(screen.queryByText(/скрыто/)).not.toBeInTheDocument();
  });

  it("counts the screens, the active ones and those on the console", async () => {
    renderPage();
    await screen.findByTestId("screen-VNA-TV-401"); // the numbers start at 0 until the data arrives

    const stats = screen.getByRole("region", { name: "Статистика экранов" });
    expect(within(stats).getByText("Экранов").nextElementSibling).toHaveTextContent("3");
    expect(within(stats).getByText("Активных").nextElementSibling).toHaveTextContent("2");
    expect(within(stats).getByText("На связи в RustDesk").nextElementSibling).toHaveTextContent("1");
  });

  it("says in words what state a machine is in, and offers the connect button on each", async () => {
    renderPage();

    const row = await screen.findByTestId("screen-VN3-TV-001");
    expect(within(row).getByText(/машина включена, RustDesk не подключён/)).toBeInTheDocument();
    expect(within(row).getByRole("button", { name: "Подключиться к VN3-TV-001" })).toBeInTheDocument();
  });

  it("finds a screen by its store name", async () => {
    renderPage();
    await screen.findByTestId("screen-VNA-TV-401");

    fireEvent.change(screen.getByPlaceholderText("Экран или магазин"), { target: { value: "внуково" } });

    expect(screen.getByTestId("screen-VN3-TV-001")).toBeInTheDocument();
    expect(screen.queryByTestId("screen-VNA-TV-401")).not.toBeInTheDocument();
  });

  it("explains an empty result instead of showing nothing", async () => {
    api.getRemoteDevices.mockResolvedValue({ data: [dev("VNA-TV-402", { online: false, host_online: false })], count: 1 });
    renderPage();

    expect(await screen.findByText(/Активных экранов нет/)).toBeInTheDocument();
  });

  it("says when there are no TV machines at all", async () => {
    api.getRemoteDevices.mockResolvedValue({ data: [dev("VNA-MGR-205")], count: 1 });
    renderPage();

    expect(await screen.findByText(/Экранов нет: в удалённом доступе нет устройств с TV/)).toBeInTheDocument();
  });
});
