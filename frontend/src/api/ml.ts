import api from "./http";

export interface MLTonerPrediction {
  id: string;
  printer_id: string | null;
  printer_name: string | null;
  toner_color: "black" | "cyan" | "magenta" | "yellow" | string;
  toner_model: string | null;
  current_level: number | null;
  days_to_replacement: number | null;
  predicted_replacement_at: string | null;
  confidence: number;
  model_version: string;
  created_at: string;
}

export interface MLOfflineRiskPrediction {
  id: string;
  device_kind: string;
  device_id: string | null;
  device_name: string | null;
  address: string | null;
  risk_score: number;
  risk_level: "low" | "medium" | "high" | string;
  confidence: number;
  model_version: string;
  created_at: string;
}

export interface MLModelStatus {
  model_family: string;
  version: string;
  status: string;
  train_rows: number;
  metric_primary: number | null;
  metric_secondary: number | null;
  trained_at: string;
  activated_at: string | null;
}

export async function getTonerPredictions(printer_id?: string) {
  const params: Record<string, string> = {};
  if (printer_id) params.printer_id = printer_id;
  const { data } = await api.get<{ data: MLTonerPrediction[]; count: number }>("/ml/predictions/toner", { params });
  return data;
}

export async function getOfflineRiskPredictions(device_kind?: string) {
  const params: Record<string, string> = {};
  if (device_kind) params.device_kind = device_kind;
  const { data } = await api.get<{ data: MLOfflineRiskPrediction[]; count: number }>("/ml/predictions/offline-risk", {
    params,
  });
  return data;
}

export async function getMLModelStatus() {
  const { data } = await api.get<{ data: MLModelStatus[]; count: number }>("/ml/models/status");
  return data;
}

export async function runMLCycle() {
  const { data } = await api.post<{ message: string }>("/ml/run-cycle");
  return data;
}
