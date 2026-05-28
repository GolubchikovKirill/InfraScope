import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";

const api = vi.hoisted(() => ({
  getSwitches: vi.fn(),
  createSwitch: vi.fn(),
  updateSwitch: vi.fn(),
  deleteSwitch: vi.fn(),
  pollSwitch: vi.fn(),
  pollAllSwitches: vi.fn(),
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

vi.mock("../components/SwitchCard", () => ({
  default: ({ sw }: { sw: { name: string } }) => <div>{sw.name}</div>,
}));

vi.mock("../components/SwitchForm", () => ({
  default: () => <div>SwitchForm</div>,
}));

vi.mock("../components/SwitchPortsTable", () => ({
  default: () => <div>SwitchPortsTable</div>,
}));

import SwitchesPage from "./SwitchesPage";

describe("SwitchesPage", () => {
  it("runs poll-all action from toolbar", async () => {
    api.getSwitches.mockResolvedValue({
      data: [
        { id: "1", name: "SW-1", ip_address: "10.0.0.1", ssh_username: "admin", ssh_port: 22, ap_vlan: 20, vendor: "cisco", management_protocol: "snmp+ssh", snmp_version: "2c", model_info: null, ios_version: null, hostname: null, uptime: null, is_online: true, last_polled_at: null, created_at: "2026-05-22T00:00:00Z" },
      ],
      count: 1,
    });
    api.pollAllSwitches.mockResolvedValue({ ok: true });

    const queryClient = new QueryClient();
    render(
      <QueryClientProvider client={queryClient}>
        <SwitchesPage />
      </QueryClientProvider>,
    );

    expect(await screen.findByText("SW-1")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Опросить все" }));

    await waitFor(() => expect(api.pollAllSwitches).toHaveBeenCalledTimes(1));
  });
});
