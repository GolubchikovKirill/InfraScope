import api from "./http";

export interface Computer {
  id: string;
  hostname: string;
  location: string | null;
  comment: string | null;
  is_online: boolean | null;
  reachability_reason: "dns_unresolved" | "port_closed" | null;
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
