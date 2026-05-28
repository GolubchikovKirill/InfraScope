import { fireEvent, render, screen } from "@testing-library/react";
import { vi } from "vitest";

import type { MediaAssignment, MediaAsset, MediaClientHeartbeat, MediaPlayer } from "../client";
import MediaAssignmentPanel from "./MediaAssignmentPanel";

const player: MediaPlayer = {
  id: "00000000-0000-0000-0000-000000000001",
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

const assignment: MediaAssignment = {
  id: "00000000-0000-0000-0000-000000000002",
  player_id: player.id,
  asset_id: null,
  title: "Hall playlist",
  media_type: "video",
  source_url: "http://media.local/hall.mp4",
  playback_mode: "loop",
  volume: 45,
  enabled: true,
  revision: 4,
  created_at: "2026-05-22T00:00:00Z",
  updated_at: "2026-05-22T01:00:00Z",
};

const mediaAsset: MediaAsset = {
  id: "00000000-0000-0000-0000-000000000004",
  title: "Airport radio",
  media_type: "audio",
  source_url: "/assets/00000000-0000-0000-0000-000000000004/file",
  original_filename: "airport-radio.mp3",
  content_type: "audio/mpeg",
  file_size_bytes: 2_400_000,
  is_active: true,
  created_at: "2026-05-22T02:00:00Z",
  updated_at: null,
};

const heartbeat: MediaClientHeartbeat = {
  id: "00000000-0000-0000-0000-000000000003",
  player_id: player.id,
  agent_version: "0.2.0",
  hostname: "hall-nettop-01",
  current_revision: 3,
  player_state: "playing",
  error_message: null,
  last_seen_at: "2026-05-22T02:00:00Z",
  created_at: "2026-05-22T02:00:00Z",
  updated_at: "2026-05-22T02:00:00Z",
};

describe("MediaAssignmentPanel", () => {
  it("submits video assignment with normalized volume and enabled state", () => {
    const onSave = vi.fn();
    render(
      <MediaAssignmentPanel
        player={player}
        assignment={assignment}
        heartbeat={heartbeat}
        saving={false}
        onClose={vi.fn()}
        onSave={onSave}
      />,
    );

    expect(screen.getByText("агент ещё не применил изменение")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Аудио/i }));
    fireEvent.change(screen.getByLabelText("URL или путь"), {
      target: { value: "http://media.local/radio.mp3" },
    });
    fireEvent.change(screen.getByLabelText("Громкость"), { target: { value: "130" } });
    fireEvent.click(screen.getByRole("button", { name: /Сохранить/i }));

    expect(onSave).toHaveBeenCalledWith({
      title: "Hall playlist",
      media_type: "audio",
      source_url: "http://media.local/radio.mp3",
      asset_id: null,
      playback_mode: "loop",
      volume: 100,
      enabled: true,
    });
  });

  it("does not submit empty media source", () => {
    const onSave = vi.fn();
    render(
      <MediaAssignmentPanel
        player={player}
        saving={false}
        onClose={vi.fn()}
        onSave={onSave}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /Сохранить/i }));

    expect(onSave).not.toHaveBeenCalled();
  });

  it("uses selected media library asset for assignment", () => {
    const onSave = vi.fn();
    render(
      <MediaAssignmentPanel
        player={player}
        assets={[mediaAsset]}
        saving={false}
        onClose={vi.fn()}
        onSave={onSave}
      />,
    );

    fireEvent.change(screen.getByRole("combobox", { name: /Файл из медиатеки/i }), {
      target: { value: mediaAsset.id },
    });
    fireEvent.click(screen.getByRole("button", { name: /Сохранить/i }));

    expect(onSave).toHaveBeenCalledWith({
      title: "Airport radio",
      media_type: "audio",
      source_url: mediaAsset.source_url,
      asset_id: mediaAsset.id,
      playback_mode: "loop",
      volume: null,
      enabled: true,
    });
  });
});
