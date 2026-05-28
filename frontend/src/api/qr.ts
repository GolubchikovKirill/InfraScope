import api from "./http";

export interface QRGeneratorPayload {
  db_mode: "duty_free" | "duty_paid" | "both";
  airport_code?: string;
  surnames?: string;
  add_login?: boolean;
}

export async function exportQrGenerator(payload: QRGeneratorPayload): Promise<Blob> {
  const { data } = await api.post("/qr-generator/export", payload, { responseType: "blob" });
  return data as Blob;
}

export interface BoardingPassPayload {
  format: "aztec" | "pdf417";
  first_name?: string;
  last_name?: string;
  booking_ref?: string;
  from_code?: string;
  to_code?: string;
  flight_operator?: string;
  flight_number?: string;
  flight_date?: string;
  day_in_year?: string;
  travel_class?: string;
  seat?: string;
  boarding_index?: string;
  raw_data?: string;
}

export async function exportBoardingPass(payload: BoardingPassPayload): Promise<Blob> {
  const { data } = await api.post("/boarding-pass/export", payload, { responseType: "blob" });
  return data as Blob;
}
