import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { vi } from "vitest";
import type { RemoteDevice } from "../client";

const api = vi.hoisted(() => ({
  getConsoleConnections: vi.fn(),
  getRemoteDevices: vi.fn(),
  requestDeploy: vi.fn(),
  rotateRemotePassword: vi.fn(),
  rustdeskLink: vi.fn((id: string) => `rustdesk://connection/new/${id}`),
  syncAddressBook: vi.fn(),
  syncRemoteAccess: vi.fn(),
  updateRemoteDevice: vi.fn(),
  setDeviceProfile: vi.fn(),
  getDeployCommand: vi.fn(),
}));

vi.mock("../client", () => api);

vi.mock("../auth", () => ({
  useAuth: () => ({ user: { is_superuser: true } }),
}));

vi.mock("../hooks/useDebouncedValue", () => ({
  useDebouncedValue: (value: string) => value,
}));

vi.mock("../components/ConsoleAccountsPanel", () => ({
  default: ({ isSuperuser }: { isSuperuser: boolean }) => (
    <div>ConsoleAccountsPanel stub · superuser={String(isSuperuser)}</div>
  ),
}));

import RemoteAccessPage from "./RemoteAccessPage";

function makeDevice(overrides: Partial<RemoteDevice> = {}): RemoteDevice {
  return {
    id: "dev-1",
    hostname: "VNK-MGR-D1",
    location: "A1",
    source_kind: "computer",
    type_tag: null,
    computer_id: null,
    media_player_id: null,
    cash_register_id: null,
    rustdesk_id: "VNK_MGR_D1",
    has_password: true,
    password_rotated_at: null,
    deploy_profile: "client",
    desired_hidden: true,
    desired_block_outgoing: true,
    desired_unattended: true,
    managed: true,
    in_address_book: false,
    ab_password_pushed: false,
    deploy_state: "unknown",
    deploy_detail: null,
    deploy_requested_at: null,
    deploy_reported_at: null,
    readiness: "not_deployed",
    installed_version: null,
    os_edition: null,
    os_caption: null,
    applocker_supported: null,
    applocker_mismatch: false,
    online: null,
    logged_in_user: null,
    last_ip: null,
    last_seen_at: null,
    host_online: null,
    host_last_seen_at: null,
    created_at: "2026-09-01T00:00:00Z",
    ...overrides,
  };
}

const renderPage = () =>
  render(
    <QueryClientProvider client={new QueryClient()}>
      <RemoteAccessPage />
    </QueryClientProvider>,
  );

beforeEach(() => {
  // hoisted mocks are shared across every `it()` here and vitest does not
  // clear call history between tests on its own (no clearMocks in the vite
  // config) - without this, later toHaveBeenCalledWith/.not.toHaveBeenCalled()
  // assertions see calls left over from an earlier test.
  vi.clearAllMocks();
  api.getConsoleConnections.mockResolvedValue([]);
});

describe("RemoteAccessPage", () => {
  it("shows per-device readiness and switches between tabs", async () => {
    api.getRemoteDevices.mockResolvedValue({
      data: [
        makeDevice({ id: "dev-1", hostname: "VNK-MGR-D1", readiness: "ready" }),
        makeDevice({ id: "dev-2", hostname: "VNA-MGR-901", readiness: "failed", deploy_detail: "msiexec exit 1603" }),
      ],
      count: 2,
    });

    renderPage();

    // the "Готово к подключению" stat card and the row chip share exact
    // wording on purpose (see docs/rustdesk-v2-plan.md) - scope to each row
    // so the assertion isn't fooled by the stat card above the table
    const readyRow = (await screen.findByText("VNK-MGR-D1")).closest("tr")!;
    expect(within(readyRow).getByText("Готово к подключению")).toBeInTheDocument();
    const failedRow = screen.getByText("VNA-MGR-901").closest("tr")!;
    expect(within(failedRow).getByText("Ошибка развёртывания")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Админы" }));
    expect(await screen.findByText(/ConsoleAccountsPanel stub/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Подключения" }));
    expect(await screen.findByText("Последние подключения")).toBeInTheDocument();
  });

  it("requests a rollout from a device row and opens the command modal", async () => {
    api.getRemoteDevices.mockResolvedValue({
      data: [makeDevice()],
      count: 1,
    });
    api.requestDeploy.mockResolvedValue(makeDevice({ deploy_state: "pending", readiness: "deploying" }));
    api.getDeployCommand.mockResolvedValue({
      command: 'powershell.exe -Command "iex ..."',
      bootstrap_url: "http://10.10.99.24:8000/api/v1/remote-access/deploy/bootstrap.ps1",
      installer_filename: "rustdesk-1.4.9-x86_64.msi",
      installer_version: "1.4.9",
      configured: true,
    });

    renderPage();
    await screen.findByText("VNK-MGR-D1");

    fireEvent.click(screen.getByTitle("Развернуть тихо через InfraScope"));
    await waitFor(() => expect(api.requestDeploy).toHaveBeenCalledWith("dev-1"));
    expect(await screen.findByText(/powershell.exe/)).toBeInTheDocument();
  });

  it("opens the KSC command from the header without touching any device", async () => {
    api.getRemoteDevices.mockResolvedValue({ data: [], count: 0 });
    api.getDeployCommand.mockResolvedValue({
      command: "powershell.exe -Command \"iex ...\"",
      bootstrap_url: "http://10.10.99.24:8000/api/v1/remote-access/deploy/bootstrap.ps1",
      installer_filename: "rustdesk-1.4.9-x86_64.msi",
      installer_version: "1.4.9",
      configured: true,
    });

    renderPage();
    fireEvent.click(await screen.findByText("Команда для KSC"));

    expect(await screen.findByText(/powershell.exe/)).toBeInTheDocument();
    expect(api.requestDeploy).not.toHaveBeenCalled();
  });

  it("disables the address-book push and shows a banner when the console is down", async () => {
    api.getRemoteDevices.mockResolvedValue({ data: [makeDevice()], count: 1 });
    api.getConsoleConnections.mockRejectedValue(new Error("502"));

    renderPage();
    expect(await screen.findByText(/Консоль RustDesk не подключена/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /В книгу адресов/ })).toBeDisabled();
  });

  it("confirms scope before a bulk address-book push", async () => {
    api.getRemoteDevices.mockResolvedValue({ data: [makeDevice()], count: 1 });
    api.syncAddressBook.mockResolvedValue({ message: "общая книга: добавлено 1" });
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);

    renderPage();
    await screen.findByText("VNK-MGR-D1");

    fireEvent.click(screen.getByRole("button", { name: /В книгу адресов/ }));
    expect(confirmSpy).toHaveBeenCalled();
    await waitFor(() => expect(api.syncAddressBook).toHaveBeenCalled());
  });

  it("banners a Windows edition mismatch with a count of affected devices", async () => {
    api.getRemoteDevices.mockResolvedValue({
      data: [
        makeDevice({ id: "dev-1", hostname: "VNA-MGR-901" }),
        makeDevice({ id: "dev-2", hostname: "VNA-MGR-902", applocker_mismatch: true, os_edition: "Core" }),
      ],
      count: 2,
    });

    renderPage();
    expect(await screen.findByText(/на Windows Home/)).toBeInTheDocument();
    expect(screen.getByText("1")).toBeInTheDocument();
  });

  it("switches a device to the admin profile from the row selector", async () => {
    api.getRemoteDevices.mockResolvedValue({ data: [makeDevice()], count: 1 });
    api.setDeviceProfile.mockResolvedValue(makeDevice({ deploy_profile: "admin" }));

    renderPage();
    const row = (await screen.findByText("VNK-MGR-D1")).closest("tr")!;
    const select = within(row).getByTitle(/AppLocker не даёт запустить самому/);
    expect(select).toHaveValue("client");

    fireEvent.change(select, { target: { value: "admin" } });
    await waitFor(() => expect(api.setDeviceProfile).toHaveBeenCalledWith("dev-1", "admin"));
  });
});
