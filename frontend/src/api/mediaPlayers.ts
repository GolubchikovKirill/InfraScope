import api from "./http";

export type DeviceType = "nettop" | "iconbit" | "twix";

export interface MediaPlayer {
  id: string;
  device_type: DeviceType;
  name: string;
  model: string;
  ip_address: string;
  mac_address: string | null;
  is_online: boolean | null;
  hostname: string | null;
  os_info: string | null;
  uptime: string | null;
  open_ports: string | null;
  last_polled_at: string | null;
  created_at: string;
}

export interface MediaPlayersResponse {
  data: MediaPlayer[];
  count: number;
}

export async function getMediaPlayers(name?: string, device_type?: DeviceType) {
  const params: Record<string, string> = {};
  if (name) params.name = name;
  if (device_type) params.device_type = device_type;
  const { data } = await api.get<MediaPlayersResponse>("/media-players/", { params });
  return data;
}

export async function createMediaPlayer(player: {
  device_type: DeviceType;
  name: string;
  model: string;
  ip_address: string;
  hostname?: string;
  mac_address?: string;
}) {
  const { data } = await api.post<MediaPlayer>("/media-players/", player);
  return data;
}

export async function updateMediaPlayer(id: string, player: Partial<MediaPlayer>) {
  const { data } = await api.patch<MediaPlayer>(`/media-players/${id}`, player);
  return data;
}

export async function deleteMediaPlayer(id: string) {
  await api.delete(`/media-players/${id}`);
}

export async function pollMediaPlayer(id: string) {
  const { data } = await api.post<MediaPlayer>(`/media-players/${id}/poll`);
  return data;
}

export async function rediscoverMediaPlayers() {
  const { data } = await api.post<MediaPlayersResponse>("/media-players/rediscover");
  return data;
}

export async function pollAllMediaPlayers(device_type?: DeviceType) {
  const params: Record<string, string> = {};
  if (device_type) params.device_type = device_type;
  const { data } = await api.post<MediaPlayersResponse>("/media-players/poll-all", null, { params });
  return data;
}

export interface IconbitStatus {
  now_playing: string | null;
  is_playing: boolean;
  state: string | null;
  position: number | null;
  duration: number | null;
  files: string[];
  free_space: string | null;
}

export async function getIconbitStatus(playerId: string) {
  const { data } = await api.get<IconbitStatus>(`/media-players/${playerId}/iconbit/status`);
  return data;
}

export async function iconbitPlay(playerId: string) {
  const { data } = await api.post(`/media-players/${playerId}/iconbit/play`);
  return data;
}

export async function iconbitStop(playerId: string) {
  const { data } = await api.post(`/media-players/${playerId}/iconbit/stop`);
  return data;
}

export async function iconbitPlayFile(playerId: string, filename: string) {
  const { data } = await api.post(`/media-players/${playerId}/iconbit/play-file`, { filename });
  return data;
}

export async function iconbitDeleteFile(playerId: string, filename: string) {
  const { data } = await api.post(`/media-players/${playerId}/iconbit/delete-file`, { filename });
  return data;
}

export async function iconbitUpload(playerId: string, file: File) {
  const form = new FormData();
  form.append("file", file);
  const { data } = await api.post(`/media-players/${playerId}/iconbit/upload`, form, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data;
}

export async function iconbitBulkPlay() {
  const { data } = await api.post("/media-players/iconbit/bulk-play");
  return data as { success: number; failed: number };
}

export async function iconbitBulkStop() {
  const { data } = await api.post("/media-players/iconbit/bulk-stop");
  return data as { success: number; failed: number };
}

export async function iconbitBulkUpload(file: File) {
  const form = new FormData();
  form.append("file", file);
  const { data } = await api.post("/media-players/iconbit/bulk-upload", form, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data as { success: number; failed: number; file: string };
}

export async function iconbitBulkDeleteFile(filename: string) {
  const { data } = await api.post("/media-players/iconbit/bulk-delete-file", { filename });
  return data as { success: number; failed: number };
}

export async function iconbitBulkPlayFile(filename: string) {
  const { data } = await api.post("/media-players/iconbit/bulk-play-file", { filename });
  return data as { success: number; failed: number };
}

export async function iconbitBulkReplace(file: File) {
  const form = new FormData();
  form.append("file", file);
  const { data } = await api.post("/media-players/iconbit/bulk-replace", form, {
    headers: { "Content-Type": "multipart/form-data" },
    timeout: 120_000,
  });
  return data as { success: number; failed: number; file: string };
}
