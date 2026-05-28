import api from "./http";

export interface OneCExchangeByBarcodePayload {
  target?: "duty_free" | "duty_paid";
  barcode: string;
  cash_register_identifier_kind?: "hostname" | "kkm_number" | "serial_number" | "inventory_number" | "cash_number";
  cash_register_identifiers?: string[];
  cash_register_hostnames?: string[];
  source?: string;
}

export interface OneCExchangeByBarcodeResponse {
  target: "duty_free" | "duty_paid" | null;
  ok: boolean;
  message: string;
  status_code: number | null;
  request_id: string | null;
  payload: Record<string, unknown> | null;
  error_kind: "validation" | "integration" | "timeout" | "config" | "unknown" | null;
}

export async function runOneCExchangeByBarcode(payload: OneCExchangeByBarcodePayload) {
  const { data } = await api.post<OneCExchangeByBarcodeResponse>("/1c-exchange/by-barcode", payload);
  return data;
}
