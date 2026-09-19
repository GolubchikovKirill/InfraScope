import api from "./http";
import type { ReachabilityReason } from "../lib/offlineReason";

export interface Computer {
  id: string;
  hostname: string;
  location: string | null;
  comment: string | null;
  is_online: boolean | null;
  reachability_reason: ReachabilityReason | null;
  last_polled_at: string | null;
  created_at: string;
}

export interface ComputersResponse {
  data: Computer[];
  count: number;
}

export async function getComputers(q?: string) {
  const params: Record<string, string> = {};
  if (q) params.q = q;
  const { data } = await api.get<ComputersResponse>("/computers/", { params });
  return data;
}

export async function createComputer(payload: {
  hostname: string;
  location?: string;
  comment?: string;
}) {
  const { data } = await api.post<Computer>("/computers/", payload);
  return data;
}

export async function updateComputer(id: string, payload: Partial<Computer>) {
  const { data } = await api.patch<Computer>(`/computers/${id}`, payload);
  return data;
}

/** A computer that is not in the RustDesk console and does not answer a ping. */
export interface StaleComputer {
  id: string;
  hostname: string;
  location: string | null;
  comment: string | null;
  is_online: boolean | null;
  last_polled_at: string | null;
  created_at: string;
  reason: string;
  /** NB / NOTE / LPT: may just be off the office network, not gone */
  laptop_like: boolean;
  in_remote_access: boolean;
}

export interface StaleComputersResponse {
  /** false when the console could not be read - nothing can be judged then */
  console_reachable: boolean;
  count: number;
  data: StaleComputer[];
}

export async function getStaleComputers() {
  const { data } = await api.get<StaleComputersResponse>("/computers/stale");
  return data;
}

export async function deleteComputer(id: string) {
  await api.delete(`/computers/${id}`);
}

export async function pollComputer(id: string) {
  const { data } = await api.post<Computer>(`/computers/${id}/poll`);
  return data;
}

export async function pollAllComputers() {
  const { data } = await api.post<ComputersResponse>("/computers/poll-all");
  return data;
}
