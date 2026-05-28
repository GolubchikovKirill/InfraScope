import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { vi } from "vitest";
import SwitchPortsTable from "./SwitchPortsTable";

const api = vi.hoisted(() => ({
  getSwitchPorts: vi.fn(),
  setSwitchPortAdminState: vi.fn(),
  setSwitchPortDescription: vi.fn(),
  setSwitchPortVlan: vi.fn(),
  setSwitchPortMode: vi.fn(),
  setSwitchPortPoe: vi.fn(),
}));

vi.mock("../client", () => ({
  getSwitchPorts: api.getSwitchPorts,
  setSwitchPortAdminState: api.setSwitchPortAdminState,
  setSwitchPortDescription: api.setSwitchPortDescription,
  setSwitchPortVlan: api.setSwitchPortVlan,
  setSwitchPortMode: api.setSwitchPortMode,
  setSwitchPortPoe: api.setSwitchPortPoe,
}));

describe("SwitchPortsTable", () => {
  it("loads ports and allows admin actions", async () => {
    api.getSwitchPorts.mockResolvedValue({
      data: [
        {
          port: "Gi0/1",
          if_index: 1,
          description: "AP",
          admin_status: "up",
          oper_status: "up",
          speed_mbps: 1000,
          duplex: null,
          vlan: 20,
          port_mode: "access",
          access_vlan: 20,
          trunk_native_vlan: null,
          trunk_allowed_vlans: null,
          poe_enabled: true,
          poe_power_w: 6.2,
          mac_count: null,
        },
      ],
      count: 1,
    });
    api.setSwitchPortAdminState.mockResolvedValue({ message: "ok" });

    const qc = new QueryClient();
    render(
      <QueryClientProvider client={qc}>
        <SwitchPortsTable
          sw={{
            id: "1",
            name: "SW-1",
            ip_address: "10.0.0.1",
            ssh_username: "admin",
            ssh_port: 22,
            ap_vlan: 20,
            vendor: "cisco",
            management_protocol: "snmp+ssh",
            snmp_version: "2c",
            model_info: null,
            ios_version: null,
            hostname: null,
            uptime: null,
            is_online: true,
            last_polled_at: null,
            created_at: new Date().toISOString(),
          }}
          isSuperuser={true}
          onClose={() => {}}
        />
      </QueryClientProvider>,
    );

    expect(await screen.findByText("Gi0/1")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Перенастроить порты" }));
    fireEvent.click(screen.getByRole("button", { name: "Down" }));
    await waitFor(() => {
      expect(api.setSwitchPortAdminState).toHaveBeenCalledWith("1", "Gi0/1", "down");
    });
  });
});
