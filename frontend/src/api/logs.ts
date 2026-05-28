import api from "./http";

export type EventSeverity = "info" | "warning" | "error" | "critical";
export type EventDeviceKind = "printer" | "media_player" | "switch" | "cash_register" | null;

export interface EventLog {
  id: string;
  severity: EventSeverity;
  category: string;
  event_type: string;
  message: string;
  device_kind: EventDeviceKind;
  device_name: string | null;
  ip_address: string | null;
  created_at: string;
}

export interface EventLogsResponse {
  data: EventLog[];
  count: number;
}

export async function getEventLogs(params?: {
  skip?: number;
  limit?: number;
  severity?: EventSeverity | "all";
  device_kind?: "printer" | "media_player" | "switch" | "cash_register" | "all";
  q?: string;
}) {
  const query: Record<string, string | number> = {
    skip: params?.skip ?? 0,
    limit: params?.limit ?? 100,
  };
  if (params?.severity && params.severity !== "all") query.severity = params.severity;
  if (params?.device_kind && params.device_kind !== "all") query.device_kind = params.device_kind;
  if (params?.q) query.q = params.q;
  const { data } = await api.get<EventLogsResponse>("/logs/", { params: query });
  return data;
}
