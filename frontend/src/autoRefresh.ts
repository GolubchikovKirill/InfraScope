export const AUTO_REFRESH_ENABLED_KEY = "infrascope:auto-refresh-enabled";
export const AUTO_REFRESH_INTERVAL_KEY = "infrascope:auto-refresh-interval-minutes-v2";
export const AUTO_REFRESH_INTERVAL_OPTIONS = [5, 10, 15] as const;
export type AutoRefreshMinutes = (typeof AUTO_REFRESH_INTERVAL_OPTIONS)[number];

const DEFAULT_ENABLED = true;
const DEFAULT_INTERVAL: AutoRefreshMinutes = 15;

export function readAutoRefreshEnabled(): boolean {
  if (typeof window === "undefined") return DEFAULT_ENABLED;
  const raw = localStorage.getItem(AUTO_REFRESH_ENABLED_KEY);
  if (raw === null) return DEFAULT_ENABLED;
  return raw !== "false";
}

export function writeAutoRefreshEnabled(enabled: boolean): void {
  if (typeof window === "undefined") return;
  localStorage.setItem(AUTO_REFRESH_ENABLED_KEY, String(enabled));
}

export function readAutoRefreshIntervalMinutes(): AutoRefreshMinutes {
  if (typeof window === "undefined") return DEFAULT_INTERVAL;
  const raw = localStorage.getItem(AUTO_REFRESH_INTERVAL_KEY);
  const parsed = Number(raw);
  if (AUTO_REFRESH_INTERVAL_OPTIONS.includes(parsed as AutoRefreshMinutes)) {
    return parsed as AutoRefreshMinutes;
  }
  return DEFAULT_INTERVAL;
}

export function writeAutoRefreshIntervalMinutes(minutes: AutoRefreshMinutes): void {
  if (typeof window === "undefined") return;
  localStorage.setItem(AUTO_REFRESH_INTERVAL_KEY, String(minutes));
}
