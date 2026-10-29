import api from "./http";

export interface HonestSignTarget {
  host: string;
  label: string;
  hostname: string | null;
  original_host: string;
}

export interface HonestSignTargetsResponse {
  data: HonestSignTarget[];
  count: number;
  status_configured: boolean;
  initialization_configured: boolean;
  auto_check_enabled: boolean;
  auto_check_interval_minutes: number;
}

export interface HonestSignStatus extends HonestSignTarget {
  reachable: boolean;
  status: string;
  version: string | null;
  ready: boolean;
  message: string;
  checked_at: string;
  // Only present on results read back from the scheduled check's store.
  state_since?: string | null;
  consecutive_failures?: number;
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

export interface HonestSignCashRegisterLink {
  cash_register_id: string;
  target: HonestSignTarget;
  status: HonestSignStatus | null;
}

export interface HonestSignCashRegistersResponse {
  data: HonestSignCashRegisterLink[];
  unmatched_targets: HonestSignTarget[];
  ambiguous_hostnames: string[];
  status_configured: boolean;
  initialization_configured: boolean;
  auto_check_enabled: boolean;
  auto_check_interval_minutes: number;
}

export async function getHonestSignCashRegisters() {
  const { data } = await api.get<HonestSignCashRegistersResponse>("/honest-sign/cash-registers");
  return data;
}

export async function getHonestSignTargets() {
  const { data } = await api.get<HonestSignTargetsResponse>("/honest-sign/targets");
  return data;
}

export async function getStoredHonestSignStatuses() {
  const { data } = await api.get<HonestSignStatusesResponse>("/honest-sign/statuses");
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

export async function updateHonestSignTargetIp(originalHost: string, newIp: string) {
  const { data } = await api.patch<HonestSignTarget>(
    `/honest-sign/${encodeURIComponent(originalHost)}/ip`,
    { new_ip: newIp },
  );
  return data;
}
