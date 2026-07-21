import api from "./http";

export interface HonestSignTarget {
  host: string;
  label: string;
  hostname: string | null;
}

export interface HonestSignTargetsResponse {
  data: HonestSignTarget[];
  count: number;
  status_configured: boolean;
  initialization_configured: boolean;
}

export interface HonestSignStatus extends HonestSignTarget {
  reachable: boolean;
  status: string;
  version: string | null;
  ready: boolean;
  message: string;
  checked_at: string;
}

export interface HonestSignStatusesResponse {
  data: HonestSignStatus[];
  count: number;
}

export interface HonestSignInitializeResult extends HonestSignTarget {
  initial_status: string;
  final_status: string;
  result: string;
  message: string;
  checked_at: string;
}

export async function getHonestSignTargets() {
  const { data } = await api.get<HonestSignTargetsResponse>("/honest-sign/targets");
  return data;
}

export async function checkAllHonestSignTargets() {
  const { data } = await api.post<HonestSignStatusesResponse>("/honest-sign/check-all");
  return data;
}

export async function checkHonestSignTarget(host: string) {
  const { data } = await api.post<HonestSignStatus>(`/honest-sign/${encodeURIComponent(host)}/check`);
  return data;
}

export async function initializeHonestSignTarget(host: string) {
  const { data } = await api.post<HonestSignInitializeResult>(`/honest-sign/${encodeURIComponent(host)}/initialize`);
  return data;
}
