import { isAxiosError } from "axios";

export function apiErrorMessage(error: unknown, fallback = "Произошла ошибка"): string {
  if (isAxiosError(error)) {
    const detail = error.response?.data?.detail;
    if (typeof detail === "string") return detail;
    if (error.message) return error.message;
  }
  if (error instanceof Error) return error.message;
  return fallback;
}
