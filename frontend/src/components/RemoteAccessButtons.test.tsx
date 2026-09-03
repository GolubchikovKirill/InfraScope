import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";
import type { RemoteDevice } from "../client";

const api = vi.hoisted(() => ({
  ensureRustDeskDevice: vi.fn(),
  getDevicePackage: vi.fn(),
  hostnameToRid: vi.fn((h: string) => h.replace(/[^A-Za-z0-9_]/g, "_").slice(0, 32)),
  requestDeploy: vi.fn(),
  rustdeskLink: vi.fn((id: string) => `rustdesk://connection/new/${id}`),
  getDeployCommand: vi.fn(),
}));

vi.mock("../client", () => api);

import RemoteAccessButtons from "./RemoteAccessButtons";

const device: RemoteDevice = {
  id: "dev-1",
  hostname: "VNK-MGR-D1",
  location: "A1",
  source_kind: "computer",
  computer_id: null,
  media_player_id: null,
  cash_register_id: null,
  rustdesk_id: "VNK_MGR_D1",
  has_password: true,
  password_rotated_at: null,
  desired_hidden: true,
  desired_block_outgoing: true,
  desired_unattended: true,
  managed: true,
  in_address_book: true,
  ab_password_pushed: true,
  deploy_state: "configured",
  deploy_detail: null,
  deploy_requested_at: null,
  deploy_reported_at: "2026-09-02T09:00:00Z",
  readiness: "ready",
  installed_version: "1.4.9",
  os_edition: "Professional",
  os_caption: "Windows 10 Pro",
  applocker_supported: true,
  applocker_mismatch: false,
  online: true,
  logged_in_user: "kassir",
  last_ip: "10.10.99.51",
  last_seen_at: "2026-09-02T09:00:00Z",
  host_online: true,
  host_last_seen_at: "2026-09-02T09:00:00Z",
  created_at: "2026-09-01T00:00:00Z",
};

const renderButtons = (overrides: Partial<Parameters<typeof RemoteAccessButtons>[0]> = {}) =>
  render(
    <QueryClientProvider client={new QueryClient()}>
      <RemoteAccessButtons hostname="VNK-MGR-D1" device={device} canManage={true} {...overrides} />
    </QueryClientProvider>,
  );

beforeEach(() => {
  // hoisted mocks are shared across every `it()` here and vitest does not
  // clear call history between tests on its own (no clearMocks in the vite
  // config) - without this, later toHaveBeenCalledWith assertions see calls
  // left over from an earlier test.
  vi.clearAllMocks();
  api.hostnameToRid.mockImplementation((h: string) => h.replace(/[^A-Za-z0-9_]/g, "_").slice(0, 32));
  api.rustdeskLink.mockImplementation((id: string) => `rustdesk://connection/new/${id}`);
});

describe("RemoteAccessButtons", () => {
  it("shows the connect link and readiness chip", () => {
    renderButtons();
    const link = screen.getByText("Подключиться").closest("a");
    expect(link).toHaveAttribute("href", "rustdesk://connection/new/VNK_MGR_D1");
    expect(screen.getByText("Готово к подключению")).toBeInTheDocument();
  });

  it("requests a rollout and opens the command modal", async () => {
    api.requestDeploy.mockResolvedValue({ ...device, deploy_state: "pending" });
    api.getDeployCommand.mockResolvedValue({
      command: 'powershell.exe -Command "iex ..."',
      bootstrap_url: "http://10.10.99.24:8000/api/v1/remote-access/deploy/bootstrap.ps1",
      installer_filename: "rustdesk-1.4.9-x86_64.msi",
      installer_version: "1.4.9",
      configured: true,
    });
    renderButtons();

    // the fixture is readiness: "ready" - already configured once, so the
    // button reads "Передеплоить" (it reapplies everything, not just the diff)
    fireEvent.click(screen.getByText("Передеплоить"));
    await waitFor(() => expect(api.requestDeploy).toHaveBeenCalledWith("dev-1"));
    expect(await screen.findByText(/powershell.exe/)).toBeInTheDocument();
  });

  it("labels the button Развернуть for a device that has never been deployed", () => {
    renderButtons({ device: { ...device, readiness: "not_deployed", deploy_state: "unknown" } });
    expect(screen.getByText("Развернуть")).toBeInTheDocument();
    expect(screen.queryByText("Передеплоить")).not.toBeInTheDocument();
  });

  it("labels the button Передеплоить for a device that needs a redeploy", () => {
    renderButtons({ device: { ...device, readiness: "stale", deploy_state: "stale" } });
    expect(screen.getByText("Передеплоить")).toBeInTheDocument();
  });

  it("flags a Windows Home device that can't enforce block_outgoing", () => {
    renderButtons({
      device: { ...device, applocker_mismatch: true, os_edition: "Core", os_caption: "Windows 10 Home" },
    });
    expect(screen.getByText("Home")).toBeInTheDocument();
  });

  it("opens the offline KSC package as a secondary action", async () => {
    api.getDevicePackage.mockResolvedValue({
      hostname: "VNK-MGR-D1",
      rustdesk_id: "VNK_MGR_D1",
      id_server: "10.10.99.24",
      relay_server: "10.10.99.24",
      api_server: "http://10.10.99.24:21114",
      key: "server-key",
      permanent_password: "kentdful",
      installer_version: "1.4.9",
      hidden: true,
      block_outgoing: true,
      unattended: true,
    });
    renderButtons();

    fireEvent.click(screen.getByTitle("Оффлайн-пакет KSC (для машин без сети до InfraScope)"));
    expect(await screen.findByText("rustdesk-ksc.json · VNK-MGR-D1")).toBeInTheDocument();
    await waitFor(() => expect(api.getDevicePackage).toHaveBeenCalledWith("dev-1"));
  });

  it("saves a custom id and password from the settings dialog", async () => {
    api.ensureRustDeskDevice.mockResolvedValue({ ...device, rustdesk_id: "VNK_MGR_D1_X" });
    renderButtons();

    fireEvent.click(screen.getByText("Настроить"));
    const pwInput = screen.getByPlaceholderText("kentdful");
    fireEvent.change(pwInput, { target: { value: "newpass123" } });
    fireEvent.click(screen.getByText("Сохранить"));

    await waitFor(() =>
      expect(api.ensureRustDeskDevice).toHaveBeenCalledWith(
        expect.objectContaining({ hostname: "VNK-MGR-D1", permanent_password: "newpass123" }),
      ),
    );
  });

  it("hides management controls when the caller cannot manage the device", () => {
    renderButtons({ canManage: false });
    expect(screen.queryByText("Настроить")).not.toBeInTheDocument();
    expect(screen.queryByText("Развернуть")).not.toBeInTheDocument();
    expect(screen.queryByText("Передеплоить")).not.toBeInTheDocument();
  });
});
