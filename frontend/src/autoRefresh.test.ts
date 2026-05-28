import {
  AUTO_REFRESH_ENABLED_KEY,
  AUTO_REFRESH_INTERVAL_KEY,
  readAutoRefreshEnabled,
  readAutoRefreshIntervalMinutes,
  writeAutoRefreshEnabled,
  writeAutoRefreshIntervalMinutes,
} from "./autoRefresh";

describe("autoRefresh storage", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("returns defaults when storage values are missing", () => {
    expect(readAutoRefreshEnabled()).toBe(true);
    expect(readAutoRefreshIntervalMinutes()).toBe(15);
  });

  it("reads and writes enabled flag", () => {
    writeAutoRefreshEnabled(false);
    expect(localStorage.getItem(AUTO_REFRESH_ENABLED_KEY)).toBe("false");
    expect(readAutoRefreshEnabled()).toBe(false);

    writeAutoRefreshEnabled(true);
    expect(localStorage.getItem(AUTO_REFRESH_ENABLED_KEY)).toBe("true");
    expect(readAutoRefreshEnabled()).toBe(true);
  });

  it("treats any non-false stored value as enabled", () => {
    localStorage.setItem(AUTO_REFRESH_ENABLED_KEY, "1");
    expect(readAutoRefreshEnabled()).toBe(true);
  });

  it("reads and writes valid interval values", () => {
    writeAutoRefreshIntervalMinutes(5);
    expect(localStorage.getItem(AUTO_REFRESH_INTERVAL_KEY)).toBe("5");
    expect(readAutoRefreshIntervalMinutes()).toBe(5);

    writeAutoRefreshIntervalMinutes(10);
    expect(localStorage.getItem(AUTO_REFRESH_INTERVAL_KEY)).toBe("10");
    expect(readAutoRefreshIntervalMinutes()).toBe(10);
  });

  it("falls back to default interval for invalid values", () => {
    localStorage.setItem(AUTO_REFRESH_INTERVAL_KEY, "7");
    expect(readAutoRefreshIntervalMinutes()).toBe(15);

    localStorage.setItem(AUTO_REFRESH_INTERVAL_KEY, "NaN");
    expect(readAutoRefreshIntervalMinutes()).toBe(15);
  });
});
