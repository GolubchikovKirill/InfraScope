import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";

import type { DhcpDiagnostics, NetworkSwitch } from "../client";
import { ConfirmProvider } from "./ConfirmDialog";
import SwitchDhcpPanel from "./SwitchDhcpPanel";

const getSwitchDhcp = vi.fn();
const updateSwitch = vi.fn();

vi.mock("../client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../client")>()),
  getSwitchDhcp: (...a: unknown[]) => getSwitchDhcp(...a),
  updateSwitch: (...a: unknown[]) => updateSwitch(...a),
}));

const sw = {
  id: "switch-1",
  name: "A30",
  ap_vlan: 20,
  vendor: "cisco",
  dhcp_clear_enabled: false,
  dhcp_clear_mode: "dry_run",
} as NetworkSwitch;

const baseDiag: DhcpDiagnostics = {
  vlan: 20,
  role: "local_server",
  pools: [{ name: "VLAN20", total_addresses: 254, leased_addresses: 3, ranges: [] }],
  bindings_total: 5,
  ap_bindings: [],
  conflicts: ["10.20.0.7"],
  helper_addresses: [],
  svi_ip: "10.20.0.1",
  snooping_enabled: false,
  snooping_vlans: [],
  arp_inspection_vlans: [],
  ip_source_guard: false,
  unsupported: [],
  planned_commands: ["clear ip dhcp conflict *"],
  skipped_reasons: [],
};

function renderPanel(over: Partial<NetworkSwitch> = {}) {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <ConfirmProvider>
        <SwitchDhcpPanel sw={{ ...sw, ...over }} />
      </ConfirmProvider>
    </QueryClientProvider>,
  );
}

describe("SwitchDhcpPanel", () => {
  beforeEach(() => {
    getSwitchDhcp.mockReset();
    updateSwitch.mockReset();
  });

  it("does not allow a manual run while the switch toggle is off", () => {
    renderPanel();
    expect(screen.getByRole("button", { name: "Запустить очистку DHCP сейчас" })).toBeDisabled();
  });

  it("shows the DHCP role and the exact commands a cleanup would send", async () => {
    getSwitchDhcp.mockResolvedValue(baseDiag);
    renderPanel({ dhcp_clear_enabled: true });

    fireEvent.click(screen.getByRole("button", { name: "Диагностика DHCP" }));

    expect(await screen.findByText("DHCP раздаёт этот свитч")).toBeInTheDocument();
    expect(screen.getByText("clear ip dhcp conflict *")).toBeInTheDocument();
    expect(screen.getByText(/занято 3 из 254/)).toBeInTheDocument();
  });

  it("explains why nothing would be cleared when the switch is not the DHCP server", async () => {
    getSwitchDhcp.mockResolvedValue({
      ...baseDiag,
      role: "external",
      planned_commands: [],
      skipped_reasons: ["switch is not the DHCP server for VLAN 20 (role=external)"],
    });
    renderPanel({ dhcp_clear_enabled: true });

    fireEvent.click(screen.getByRole("button", { name: "Диагностика DHCP" }));

    expect(await screen.findByText(/Очистка ничего не сделает/)).toBeInTheDocument();
  });

  it("warns when snooping is combined with ARP inspection on the AP VLAN", async () => {
    getSwitchDhcp.mockResolvedValue({
      ...baseDiag,
      snooping_enabled: true,
      snooping_vlans: [20],
      arp_inspection_vlans: [20],
    });
    renderPanel({ dhcp_clear_enabled: true });

    fireEvent.click(screen.getByRole("button", { name: "Диагностика DHCP" }));

    expect(await screen.findByText(/ARP inspection/)).toBeInTheDocument();
  });

  it("toggles the schedule through the switch update API", async () => {
    updateSwitch.mockResolvedValue({});
    renderPanel();
    fireEvent.click(screen.getByRole("switch", { name: "Очистка DHCP по расписанию" }));
    await waitFor(() =>
      expect(updateSwitch).toHaveBeenCalledWith("switch-1", { dhcp_clear_enabled: true }),
    );
  });
});
