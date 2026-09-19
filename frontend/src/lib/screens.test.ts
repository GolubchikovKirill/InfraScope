import { describe, expect, it } from "vitest";
import type { CashRegister, RemoteDevice } from "../client";
import { filterScreenZones, groupScreens, isActiveScreen, isScreen, screenState } from "./screens";

const dev = (hostname: string, over: Partial<RemoteDevice> = {}): RemoteDevice =>
  ({
    id: hostname,
    hostname,
    location: null,
    type_tag: hostname.split("-")[1]?.toUpperCase() ?? null,
    online: true,
    host_online: true,
    ...over,
  }) as RemoteDevice;

const cash = (host: string, store: string, zone: "DF" | "DP"): CashRegister =>
  ({ id: host, hostname: host, store_number: store, location_zone: zone, kkm_number: "1", is_online: true, source_order: null }) as CashRegister;

describe("isScreen", () => {
  it("is a TV box by the role token of its name, in any letter case", () => {
    expect(isScreen({ type_tag: "TV" })).toBe(true);
    expect(isScreen({ type_tag: "tv" })).toBe(true);
    expect(isScreen({ type_tag: "MGR" })).toBe(false);
    expect(isScreen({ type_tag: null })).toBe(false);
  });
});

describe("screenState", () => {
  it.each([
    [{ online: true, host_online: false }, "online", true],
    [{ online: false, host_online: true }, "reachable", true],
    [{ online: null, host_online: true }, "reachable", true],
    [{ online: false, host_online: false }, "offline", false],
    [{ online: false, host_online: null }, "offline", false],
    [{ online: null, host_online: null }, "unknown", false],
  ])("%j -> %s (active: %s)", (input, state, active) => {
    expect(screenState(input)).toBe(state);
    expect(isActiveScreen(input)).toBe(active);
  });
});

describe("groupScreens", () => {
  const registers = [cash("VNA-KKM-401", "A4(202)", "DF"), cash("VNA-KKM-1101", "A11(209)", "DP")];
  const screens = [
    dev("VNA-TV-402", { online: false, host_online: false }),
    dev("VNA-TV-401"),
    dev("vna-tv-1101"),
    dev("VN3-TV-001"),
    dev("VNA-TV-9999", { location: "A31" }),
  ];

  it("puts each screen under the store the cash registers know, by the number in its name", () => {
    const zones = groupScreens(screens, registers);

    expect(zones.map((z) => z.label)).toEqual(["Duty Free", "Duty Paid", "Другие магазины"]);
    expect(zones[0].stores[0].label).toBe("A4(202)");
    expect(zones[0].stores[0].screens.map((s) => s.hostname)).toEqual(["VNA-TV-401", "VNA-TV-402"]);
    expect(zones[1].stores[0].label).toBe("A11(209)");
  });

  it("names Внуково 3 and trusts a location on the record", () => {
    const other = groupScreens(screens, registers)[2].stores;

    expect(other.map((s) => s.title)).toEqual(["A31", "VN3 · Внуково 3"]);
  });

  it("counts the active screens per zone", () => {
    const [df] = groupScreens(screens, registers);

    expect(df).toMatchObject({ total: 2, active: 1 });
  });
});

describe("filterScreenZones", () => {
  const zones = groupScreens(
    [dev("VNA-TV-401"), dev("VNA-TV-402", { online: false, host_online: false }), dev("VN3-TV-001")],
    [cash("VNA-KKM-401", "A4(202)", "DF")],
  );

  it("returns everything for an empty search", () => {
    expect(filterScreenZones(zones, "  ")).toBe(zones);
  });

  it("finds a screen by its name and redoes the counts", () => {
    const result = filterScreenZones(zones, "tv-402");

    expect(result).toHaveLength(1);
    expect(result[0].stores[0].screens.map((s) => s.hostname)).toEqual(["VNA-TV-402"]);
    expect(result[0]).toMatchObject({ total: 1, active: 0 });
  });

  it("keeps every screen of a store whose name or code matches", () => {
    expect(filterScreenZones(zones, "внуково")[0].stores[0].screens.map((s) => s.hostname)).toEqual(["VN3-TV-001"]);
    expect(filterScreenZones(zones, "a4(")[0].stores[0].screens).toHaveLength(2);
  });

  it("drops zones with no match", () => {
    expect(filterScreenZones(zones, "nothing-like-this")).toEqual([]);
  });
});
