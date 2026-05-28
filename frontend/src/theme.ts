export type ThemeMode = "light" | "dark";
export type DensityMode = "compact";

const THEME_KEY = "infrascope:theme-mode";

function detectPreferredTheme(): ThemeMode {
  if (typeof window === "undefined") return "light";
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function readThemeMode(): ThemeMode {
  if (typeof window === "undefined") return "light";
  const raw = localStorage.getItem(THEME_KEY);
  if (raw === "light" || raw === "dark") return raw;
  return detectPreferredTheme();
}

export function applyThemeMode(mode: ThemeMode): void {
  if (typeof document === "undefined") return;
  document.documentElement.setAttribute("data-theme", mode);
}

export function setThemeMode(mode: ThemeMode): void {
  if (typeof window !== "undefined") {
    localStorage.setItem(THEME_KEY, mode);
  }
  applyThemeMode(mode);
}

export function initThemeMode(): ThemeMode {
  const mode = readThemeMode();
  applyThemeMode(mode);
  return mode;
}

export function readDensityMode(): DensityMode {
  return "compact";
}

export function applyDensityMode(mode: DensityMode): void {
  if (typeof document === "undefined") return;
  document.documentElement.setAttribute("data-density", mode);
}

export function setDensityMode(mode: DensityMode): void {
  applyDensityMode(mode);
}

export function initDensityMode(): DensityMode {
  const mode = readDensityMode();
  applyDensityMode(mode);
  return mode;
}
