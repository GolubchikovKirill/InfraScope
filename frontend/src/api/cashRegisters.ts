import api from "./http";

export interface CashRegister {
  id: string;
  source_order: number | null;
  location_zone: "DF" | "DP" | null;
  kkm_number: string;
  store_number: string | null;
  store_code: string | null;
  sber_store_code: string | null;
  serial_number: string | null;
  inventory_number: string | null;
  terminal_id_rs: string | null;
  terminal_id_sber: string | null;
  windows_version: string | null;
  kkm_type: "retail" | "shtrih";
  rosenzweig_number: string | null;
  cash_number: string | null;
  hostname: string;
  netsupport_target: string | null;
  second_screen: string | null;
  piot_status: string | null;
  cash_drawer: string | null;
  terminal_status: string | null;
  comment: string | null;
  is_online: boolean | null;
  reachability_reason: "dns_unresolved" | "port_closed" | null;
  last_polled_at: string | null;
  created_at: string;
}

export interface CashRegistersResponse {
  data: CashRegister[];
  count: number;
}

export async function getCashRegisters(q?: string) {
  const params: Record<string, string> = {};
  if (q) params.q = q;
  const { data } = await api.get<CashRegistersResponse>("/cash-registers/", { params });
  return data;
}

export async function createCashRegister(payload: {
  source_order?: number;
  location_zone?: "DF" | "DP";
  kkm_number: string;
  store_number?: string;
  store_code?: string;
  sber_store_code?: string;
  serial_number?: string;
  inventory_number?: string;
  terminal_id_rs?: string;
  terminal_id_sber?: string;
  windows_version?: string;
  kkm_type: "retail" | "shtrih";
  rosenzweig_number?: string;
  cash_number?: string;
  hostname: string;
  netsupport_target?: string;
  second_screen?: string;
  piot_status?: string;
  cash_drawer?: string;
  terminal_status?: string;
  comment?: string;
}) {
  const { data } = await api.post<CashRegister>("/cash-registers/", payload);
  return data;
}

export async function updateCashRegister(id: string, payload: Partial<CashRegister>) {
  const { data } = await api.patch<CashRegister>(`/cash-registers/${id}`, payload);
  return data;
}

export async function deleteCashRegister(id: string) {
  await api.delete(`/cash-registers/${id}`);
}

export async function pollCashRegister(id: string) {
  const { data } = await api.post<CashRegister>(`/cash-registers/${id}/poll`);
  return data;
}

export async function pollAllCashRegisters() {
  const { data } = await api.post<CashRegistersResponse>("/cash-registers/poll-all");
  return data;
}

export function getCashRegistersExportUrl(q?: string) {
  const query = q ? `?q=${encodeURIComponent(q)}` : "";
  return `/api/v1/cash-registers/export${query}`;
}
