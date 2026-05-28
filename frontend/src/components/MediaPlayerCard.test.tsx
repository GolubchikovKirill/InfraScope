import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";

import type { MediaPlayer } from "../client";
import MediaPlayerCard from "./MediaPlayerCard";

const player: MediaPlayer = {
  id: "00000000-0000-0000-0000-000000000111",
  device_type: "nettop",
  name: "Hall Nettop",
  model: "Intel NUC",
  ip_address: "10.10.98.50",
  mac_address: "aa:bb:cc:dd:ee:50",
  is_online: true,
  hostname: "hall-nettop-01",
  os_info: "Windows 10",
  uptime: null,
  open_ports: null,
  last_polled_at: null,
  created_at: "2026-05-22T00:00:00Z",
};

describe("MediaPlayerCard", () => {
  it("copies UUID and hostname to clipboard", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText },
      configurable: true,
    });

    render(
      <MediaPlayerCard
        player={player}
        onPoll={vi.fn()}
        onEdit={vi.fn()}
        onDelete={vi.fn()}
        onManageMedia={vi.fn()}
        isPolling={false}
        isSuperuser={true}
      />,
    );

    fireEvent.click(screen.getByLabelText("Скопировать UUID устройства"));
    await waitFor(() => {
      expect(writeText).toHaveBeenCalledWith(player.id);
    });

    fireEvent.click(screen.getByTitle("Скопировать hostname для NetSupport"));
    await waitFor(() => {
      expect(writeText).toHaveBeenCalledWith("hall-nettop-01");
    });
  });

  it("invokes manage and poll actions from card controls", () => {
    const onPoll = vi.fn();
    const onManageMedia = vi.fn();

    render(
      <MediaPlayerCard
        player={player}
        onPoll={onPoll}
        onEdit={vi.fn()}
        onDelete={vi.fn()}
        onManageMedia={onManageMedia}
        isPolling={false}
        isSuperuser={true}
      />,
    );

    fireEvent.click(screen.getByTitle("Настроить централизованное медиа"));
    expect(onManageMedia).toHaveBeenCalledWith(player);

    fireEvent.click(screen.getByTitle("Опросить"));
    expect(onPoll).toHaveBeenCalledWith(player.id);
  });

  it("closes additional actions menu on outside click and Escape", async () => {
    render(
      <MediaPlayerCard
        player={player}
        onPoll={vi.fn()}
        onEdit={vi.fn()}
        onDelete={vi.fn()}
        onManageMedia={vi.fn()}
        isPolling={false}
        isSuperuser={true}
      />,
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
