import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";

import type { NetworkSwitch } from "../client";
import SwitchCard from "./SwitchCard";
import { ConfirmProvider } from "./ConfirmDialog";

const sw: NetworkSwitch = {
  id: "switch-1",
  name: "SW-Core-01",
  ip_address: "10.10.98.10",
  ssh_username: "admin",
  ssh_port: 22,
  ap_vlan: 20,
  vendor: "cisco",
  management_protocol: "snmp+ssh",
  snmp_version: "2c",
  model_info: "C9200",
  ios_version: "17.9",
  hostname: "sw-core-01",
  uptime: "3 days",
  is_online: true,
  last_polled_at: null,
  mac_address: null,
  mac_status: null,
  auto_reboot_aps_enabled: false,
  auto_reboot_mode: "dry_run",
  switch_needs_attention_since: null,
  created_at: "2026-05-22T00:00:00Z",
};

describe("SwitchCard", () => {
  it("closes additional actions menu on outside click and Escape", async () => {
    const qc = new QueryClient();
    render(
      <QueryClientProvider client={qc}>
        <ConfirmProvider>
          <SwitchCard
            sw={sw}
            onPoll={vi.fn()}
            onEdit={vi.fn()}
            onDelete={vi.fn()}
            onOpenPorts={vi.fn()}
            isPolling={false}
            isSuperuser={true}
          />
        </ConfirmProvider>
      </QueryClientProvider>,
    );

    fireEvent.click(screen.getByTitle("Дополнительные действия"));
    expect(screen.getByText("Редактировать")).toBeInTheDocument();

    fireEvent.pointerDown(document.body);
    await waitFor(() => {
      expect(screen.queryByText("Редактировать")).not.toBeInTheDocument();
    });

    fireEvent.click(screen.getByTitle("Дополнительные действия"));
    expect(screen.getByText("Редактировать")).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });

    await waitFor(() => {
      expect(screen.queryByText("Редактировать")).not.toBeInTheDocument();
    });
  });
});
