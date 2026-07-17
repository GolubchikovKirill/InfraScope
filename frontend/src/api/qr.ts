import api from "./http";

export async function normalizeDownloadError(error: unknown, fallback: string): Promise<Error> {
  const httpError = error as {
    message?: string;
    response?: { data?: unknown };
  };
  const data = httpError?.response?.data;
  const blobLike = data as { text?: () => Promise<string> } | undefined;
  if (typeof blobLike?.text === "function") {
    try {
      const body = JSON.parse(await blobLike.text()) as { detail?: string };
      if (body.detail) return new Error(body.detail);
    } catch {
      // The response is not a JSON API error; use the fallback below.
    }
  }

  const detail = (data as { detail?: string } | undefined)?.detail;
  return new Error(detail || httpError?.message || fallback);
}

export interface QRGeneratorPayload {
  db_mode: "duty_free" | "duty_paid" | "both";
  airport_code?: string;
  surnames?: string;
  add_login?: boolean;
}

export async function exportQrGenerator(payload: QRGeneratorPayload): Promise<Blob> {
  try {
    const { data } = await api.post("/qr-generator/export", payload, { responseType: "blob" });
    return data as Blob;
  } catch (error) {
    throw await normalizeDownloadError(error, "Не удалось сформировать выгрузку.");
  }
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
  try {
    const { data } = await api.post("/boarding-pass/export", payload, { responseType: "blob" });
    return data as Blob;
  } catch (error) {
    throw await normalizeDownloadError(error, "Не удалось сформировать boarding pass.");
  }
}
