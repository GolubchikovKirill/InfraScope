import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";

const api = vi.hoisted(() => ({
  addDiscoveredIconbit: vi.fn(),
  addDiscoveredPrinter: vi.fn(),
  addDiscoveredSwitch: vi.fn(),
  createCashRegister: vi.fn(),
  createComputer: vi.fn(),
  getIconbitDiscoveryResults: vi.fn(),
  getScanResults: vi.fn(),
  getScannerSettings: vi.fn(),
  getSwitchDiscoveryResults: vi.fn(),
  smartSearchCashRegistersInNetwork: vi.fn(),
  smartSearchComputersInNetwork: vi.fn(),
  startIconbitDiscoveryScan: vi.fn(),
  startScan: vi.fn(),
  startSwitchDiscoveryScan: vi.fn(),
}));

vi.mock("../auth", () => ({
  useAuth: () => ({
    user: { is_superuser: true },
  }),
}));

vi.mock("../client", () => api);

import NetworkSearchPage from "./NetworkSearchPage";

describe("NetworkSearchPage", () => {
  it("runs smart computer search and adds discovered host as computer", async () => {
    api.getScannerSettings.mockResolvedValue({ subnet: "10.10.98.0/24" });
    api.smartSearchComputersInNetwork.mockResolvedValue({
      data: [
        {
          ip: "10.10.98.25",
          hostname: "PC-MGR-025",
          open_ports: [445, 3389],
          confidence: "high",
          reason: "host found",
        },
      ],
      count: 1,
    });
    api.createComputer.mockResolvedValue({
      id: "c-1",
      hostname: "PC-MGR-025",
      location: "",
      comment: "Добавлено из поиска в сети",
      is_online: null,
      last_polled_at: null,
      created_at: "2026-05-22T00:00:00Z",
    });

    render(<NetworkSearchPage />);

    fireEvent.click(screen.getByRole("button", { name: "Запустить поиск" }));

    expect(await screen.findByText("PC-MGR-025")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Добавить в "Компьютеры"/i }));

    await waitFor(() =>
      expect(api.createComputer).toHaveBeenCalledWith({
        hostname: "PC-MGR-025",
        location: "",
        comment: "Добавлено из поиска в сети",
      }),
    );
  });
});
