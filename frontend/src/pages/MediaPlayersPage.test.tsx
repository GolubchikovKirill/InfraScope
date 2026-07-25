import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";

const api = vi.hoisted(() => ({
  getMediaPlayers: vi.fn(),
  pollAllMediaPlayers: vi.fn(),
  pollMediaPlayer: vi.fn(),
  createMediaPlayer: vi.fn(),
  updateMediaPlayer: vi.fn(),
  deleteMediaPlayer: vi.fn(),
  getMediaAssignments: vi.fn(),
  getMediaAssets: vi.fn(),
  getMediaClientHeartbeats: vi.fn(),
  iconbitBulkPlay: vi.fn(),
  iconbitBulkStop: vi.fn(),
  iconbitBulkUpload: vi.fn(),
  iconbitBulkReplace: vi.fn(),
  setMediaAssignment: vi.fn(),
  uploadMediaAsset: vi.fn(),
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

vi.mock("../components/MediaPlayerCard", () => ({
  default: ({ player }: { player: { name: string } }) => <div>{player.name}</div>,
}));

vi.mock("../components/MediaPlayerForm", () => ({
  default: () => <div>MediaPlayerForm</div>,
}));

vi.mock("../components/MediaAssignmentPanel", () => ({
  default: () => <div>MediaAssignmentPanel</div>,
}));

import MediaPlayersPage from "./MediaPlayersPage";
import { ConfirmProvider } from "../components/ConfirmDialog";

describe("MediaPlayersPage", () => {
  it("shows iconbit bulk controls and runs bulk stop", async () => {
    api.getMediaPlayers.mockResolvedValue({
      data: [
        {
          id: "player-1",
          device_type: "iconbit",
          name: "Iconbit Hall",
          model: "IB-100",
          ip_address: "10.0.0.20",
          mac_address: null,
          is_online: true,
          hostname: null,
          os_info: null,
          uptime: null,
          open_ports: null,
          last_polled_at: null,
          created_at: "2026-05-22T00:00:00Z",
        },
      ],
      count: 1,
    });
    api.getMediaAssignments.mockResolvedValue({ data: [], count: 0 });
    api.getMediaAssets.mockResolvedValue({ data: [], count: 0 });
    api.getMediaClientHeartbeats.mockResolvedValue({ data: [], count: 0 });
    api.iconbitBulkStop.mockResolvedValue({ success: 1, failed: 0 });

    const queryClient = new QueryClient();
    render(
      <QueryClientProvider client={queryClient}>
        <ConfirmProvider>
          <MediaPlayersPage />
        </ConfirmProvider>
      </QueryClientProvider>,
    );

    expect(await screen.findByText("Iconbit Hall")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Iconbit" }));
    expect(await screen.findByText("Управление всеми Iconbit")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Stop все/i }));
    await waitFor(() => expect(api.iconbitBulkStop).toHaveBeenCalledTimes(1));
  });
});
