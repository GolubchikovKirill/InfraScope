import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import type { RemoteDevice } from "../client";

const api = vi.hoisted(() => ({
  deleteRemoteDevice: vi.fn(),
  ensureRustDeskDevice: vi.fn(),
  getAddressBookStatus: vi.fn(),
  getConsoleConnections: vi.fn(),
  getRemoteDevices: vi.fn(),
  getPushJobs: vi.fn(),
  cancelPushJob: vi.fn(),
  pushDevices: vi.fn(),
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

vi.mock("../components/UnlistedConsolePeersPanel", () => ({
  default: ({ isSuperuser }: { isSuperuser: boolean }) => (
    <div>UnlistedConsolePeersPanel stub · superuser={String(isSuperuser)}</div>
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
    <MemoryRouter>
      <QueryClientProvider client={new QueryClient()}>
        <RemoteAccessPage />
      </QueryClientProvider>
    </MemoryRouter>,
  );

beforeEach(() => {
  // hoisted mocks are shared across every `it()` here and vitest does not
  // clear call history between tests on its own (no clearMocks in the vite
  // config) - without this, later toHaveBeenCalledWith/.not.toHaveBeenCalled()
  // assertions see calls left over from an earlier test.
  vi.clearAllMocks();
  api.getConsoleConnections.mockResolvedValue([]);
  api.getAddressBookStatus.mockResolvedValue({
    name: "InfraScope",
    collection_id: 1,
    owner_user_id: 1,
    entries: 0,
    shared_with_group: "InfraScope Admins",
    accounts: 1,
    missing: 0,
  });
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

  it("keeps the store TVs out of the device list and points to the Screens tab", async () => {
    api.getRemoteDevices.mockResolvedValue({
      data: [
        makeDevice({ id: "d1", hostname: "VNA-MGR-205", type_tag: "MGR" }),
        makeDevice({ id: "d2", hostname: "VNA-TV-401", type_tag: "TV" }),
        makeDevice({ id: "d3", hostname: "vna-tv-2002", type_tag: "TV" }),
      ],
      count: 3,
    });

    renderPage();

    expect(await screen.findByText("VNA-MGR-205")).toBeInTheDocument();
    expect(screen.queryByText("VNA-TV-401")).not.toBeInTheDocument();
    expect(screen.getByText(/Телевизоры \(2\) вынесены во вкладку/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "«Экраны»" })).toHaveAttribute("href", "/screens");
  });

  it("brings the TVs back into the list on request", async () => {
    api.getRemoteDevices.mockResolvedValue({
      data: [makeDevice({ id: "d1", hostname: "VNA-MGR-205", type_tag: "MGR" }), makeDevice({ id: "d2", hostname: "VNA-TV-401", type_tag: "TV" })],
      count: 2,
    });
    renderPage();
    await screen.findByText("VNA-MGR-205");

    fireEvent.click(screen.getByLabelText("Показывать и здесь"));

    expect(await screen.findByText("VNA-TV-401")).toBeInTheDocument();
  });

  it("does not mention screens when there are none", async () => {
    api.getRemoteDevices.mockResolvedValue({ data: [makeDevice({ id: "d1", hostname: "VNA-MGR-205", type_tag: "MGR" })], count: 1 });
    renderPage();

    await screen.findByText("VNA-MGR-205");
    expect(screen.queryByText(/вынесены во вкладку/)).not.toBeInTheDocument();
  });

  it("queues a dry run for every managed device in the list after a confirmation", async () => {
    api.getRemoteDevices.mockResolvedValue({
      data: [
        makeDevice({ id: "d1", hostname: "VNA-KKM-701", type_tag: "KKM" }),
        makeDevice({ id: "d2", hostname: "VNA-KKM-702", type_tag: "KKM" }),
      ],
      count: 2,
    });
    api.getPushJobs.mockResolvedValue({ data: [], count: 0, runner: { name: null, seconds_ago: null, online: false } });
    api.pushDevices.mockResolvedValue({ queued: [{ hostname: "VNA-KKM-701" }, { hostname: "VNA-KKM-702" }], skipped: [] });
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    renderPage();
    await screen.findByText("VNA-KKM-701");

    fireEvent.click(screen.getByRole("button", { name: /Пробный прогон/ }));

    await waitFor(() => expect(api.pushDevices).toHaveBeenCalledWith({ device_ids: ["d1", "d2"], dry_run: true }));
    expect(confirm.mock.calls[0][0]).toMatch(/Пробный прогон.*2 устройств/);
    confirm.mockRestore();
  });

  it("queues nothing when the confirmation is declined", async () => {
    api.getRemoteDevices.mockResolvedValue({ data: [makeDevice({ id: "d1", hostname: "VNA-KKM-701", type_tag: "KKM" })], count: 1 });
    api.getPushJobs.mockResolvedValue({ data: [], count: 0, runner: { name: null, seconds_ago: null, online: false } });
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    renderPage();
    await screen.findByText("VNA-KKM-701");

    fireEvent.click(screen.getByRole("button", { name: /Развернуть по сети/ }));

    expect(confirm).toHaveBeenCalled();
    expect(api.pushDevices).not.toHaveBeenCalled();
    confirm.mockRestore();
  });

  it("shows the network push queue for a superuser", async () => {
    api.getRemoteDevices.mockResolvedValue({ data: [makeDevice()], count: 1 });
    api.getPushJobs.mockResolvedValue({ data: [], count: 0, runner: { name: null, seconds_ago: null, online: false } });
    renderPage();

    expect(await screen.findByRole("region", { name: "Раскатка по сети" })).toBeInTheDocument();
  });

  it("offers the console machines that are not in the list on the devices tab", async () => {
    api.getRemoteDevices.mockResolvedValue({ data: [makeDevice()], count: 1 });

    renderPage();

    expect(await screen.findByText("VNK-MGR-D1")).toBeInTheDocument();
    expect(screen.getByText(/UnlistedConsolePeersPanel stub · superuser=true/)).toBeInTheDocument();

    // it belongs to the devices list, not to the accounts tab
    fireEvent.click(screen.getByRole("button", { name: "Админы" }));
    await screen.findByText(/ConsoleAccountsPanel stub/);
    expect(screen.queryByText(/UnlistedConsolePeersPanel stub/)).not.toBeInTheDocument();
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

  it("opens the deploy command from the header without touching any device", async () => {
    api.getRemoteDevices.mockResolvedValue({ data: [], count: 0 });
    api.getDeployCommand.mockResolvedValue({
      command: "powershell.exe -Command \"iex ...\"",
      bootstrap_url: "http://10.10.99.24:8000/api/v1/remote-access/deploy/bootstrap.ps1",
      installer_filename: "rustdesk-1.4.9-x86_64.msi",
      installer_version: "1.4.9",
      configured: true,
    });

    renderPage();
    fireEvent.click(await screen.findByText("Команда развёртывания"));

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

  it("banners devices the console has lost from the shared address book", async () => {
    api.getRemoteDevices.mockResolvedValue({ data: [makeDevice()], count: 1 });
    api.getAddressBookStatus.mockResolvedValue({
      name: "InfraScope",
      collection_id: 1,
      owner_user_id: 1,
      entries: 10,
      shared_with_group: "InfraScope Admins",
      accounts: 1,
      missing: 3,
    });

    renderPage();
    expect(await screen.findByText(/в консоли этой записи сейчас нет/)).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
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

  it("deletes a device after confirmation", async () => {
    api.getRemoteDevices.mockResolvedValue({ data: [makeDevice()], count: 1 });
    api.deleteRemoteDevice.mockResolvedValue({ message: "VNK-MGR-D1: удалено из удалённого доступа" });
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);

    renderPage();
    const row = (await screen.findByText("VNK-MGR-D1")).closest("tr")!;
    fireEvent.click(within(row).getByTitle("Удалить из удалённого доступа"));

    expect(confirmSpy).toHaveBeenCalled();
    await waitFor(() => expect(api.deleteRemoteDevice).toHaveBeenCalledWith("dev-1"));
  });

  it("does not delete a device when the confirmation is declined", async () => {
    api.getRemoteDevices.mockResolvedValue({ data: [makeDevice()], count: 1 });
    vi.spyOn(window, "confirm").mockReturnValue(false);

    renderPage();
    const row = (await screen.findByText("VNK-MGR-D1")).closest("tr")!;
    fireEvent.click(within(row).getByTitle("Удалить из удалённого доступа"));

    expect(api.deleteRemoteDevice).not.toHaveBeenCalled();
  });

  it("adds a device by hostname from the header button", async () => {
    api.getRemoteDevices.mockResolvedValue({ data: [], count: 0 });
    api.ensureRustDeskDevice.mockResolvedValue(makeDevice({ id: "dev-9", hostname: "VNA-KKM-9999" }));

    renderPage();
    fireEvent.click(await screen.findByText("Добавить устройство"));
    fireEvent.change(screen.getByPlaceholderText("VNA-KKM-1507"), { target: { value: "VNA-KKM-9999" } });
    fireEvent.click(screen.getByRole("button", { name: "Добавить" }));

    await waitFor(() =>
      expect(api.ensureRustDeskDevice).toHaveBeenCalledWith({ hostname: "VNA-KKM-9999" }),
    );
  });
});
