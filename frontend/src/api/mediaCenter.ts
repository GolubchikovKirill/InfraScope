import api from "./http";

export type MediaKind = "stream" | "video" | "audio";
export type PlaybackMode = "loop" | "once" | "scheduled";
export type MediaPlayerState = "idle" | "disabled" | "playing" | "error" | "unknown";

export interface MediaAssignment {
  id: string;
  player_id: string;
  asset_id: string | null;
  title: string;
  media_type: MediaKind | string;
  source_url: string;
  playback_mode: PlaybackMode | string;
  volume: number | null;
  enabled: boolean;
  revision: number;
  created_at: string;
  updated_at: string | null;
}

export interface MediaAssignmentsResponse {
  data: MediaAssignment[];
  count: number;
}

export interface MediaAssignmentPayload {
  title: string;
  media_type: MediaKind;
  source_url: string;
  asset_id?: string | null;
  playback_mode: PlaybackMode;
  volume?: number | null;
  enabled: boolean;
}

export interface MediaAsset {
  id: string;
  title: string;
  media_type: MediaKind | string;
  source_url: string;
  original_filename: string | null;
  content_type: string | null;
  file_size_bytes: number | null;
  is_active: boolean;
  created_at: string;
  updated_at: string | null;
}

export interface MediaAssetsResponse {
  data: MediaAsset[];
  count: number;
}

export interface MediaClientHeartbeat {
  id: string;
  player_id: string;
  agent_version: string | null;
  hostname: string | null;
  current_revision: number | null;
  player_state: MediaPlayerState | string;
  error_message: string | null;
  last_seen_at: string;
  created_at: string;
  updated_at: string | null;
}

export interface MediaClientHeartbeatsResponse {
  data: MediaClientHeartbeat[];
  count: number;
}

export async function getMediaAssignments() {
  const { data } = await api.get<MediaAssignmentsResponse>("/media-center/assignments");
  return data;
}

export async function getMediaAssets() {
  const { data } = await api.get<MediaAssetsResponse>("/media-center/assets");
  return data;
}

export async function uploadMediaAsset(file: File, title?: string) {
  const form = new FormData();
  form.append("file", file);
  if (title) form.append("title", title);
  const { data } = await api.post<MediaAsset>("/media-center/assets", form, {
    headers: { "Content-Type": "multipart/form-data" },
    timeout: 120_000,
  });
  return data;
}

export async function setMediaAssignment(playerId: string, payload: MediaAssignmentPayload) {
  const { data } = await api.put<MediaAssignment>(`/media-center/assignments/${playerId}`, payload);
  return data;
}

export async function updateMediaAssignment(playerId: string, payload: Partial<MediaAssignmentPayload>) {
  const { data } = await api.patch<MediaAssignment>(`/media-center/assignments/${playerId}`, payload);
  return data;
}

export async function getMediaClientHeartbeats() {
  const { data } = await api.get<MediaClientHeartbeatsResponse>("/media-center/heartbeats");
  return data;
}
