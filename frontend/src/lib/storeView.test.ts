import { describe, expect, it } from "vitest";
import type { CashRegister, Computer } from "../client";
import { buildStoreIndex, computerTile, computerView, hostnameStoreCode, placeComputer } from "./storeView";
import { storeCode, storeTitle } from "./stores";

const cash = (host: string, store: string, zone: "DF" | "DP", over: Partial<CashRegister> = {}): CashRegister =>
  ({ id: host, hostname: host, store_number: store, location_zone: zone, kkm_number: "1", is_online: true, source_order: null, ...over }) as CashRegister;

const pc = (hostname: string, over: Partial<Computer> = {}): Computer =>
  ({ id: hostname, hostname, location: null, comment: null, is_online: true, reachability_reason: null, last_polled_at: null, ...over }) as Computer;

describe("storeCode / storeTitle", () => {
  it("reads the store code out of the labels people typed", () => {
    expect(storeCode("A2(200)")).toBe("A2");
    expect(storeCode("А15")).toBe("A15"); // Cyrillic А
    expect(storeCode("A14пп")).toBe("A14");
    expect(storeCode("VN3")).toBe("VN3");
    expect(storeCode("D1")).toBe("D1");
    expect(storeCode("BUH")).toBeNull();
    expect(storeCode(null)).toBeNull();
  });

  it("names the stores we know", () => {
    expect(storeTitle("VN3")).toBe("VN3 · Внуково 3");
    expect(storeTitle("A2(200)")).toBe("A2(200)");
  });
});

describe("hostnameStoreCode", () => {
  it.each([
    ["VNA-MGR-205", "A2"],
    ["VNA-MGR-1505", "A15"],
    ["VNA-MGR-3002", "A30"],
    ["VNK-KKM-0207", "A2"],
    ["VNK-KKM-3301", "A33"],
    ["VNA-TV-601TMP", "A6"],
    ["VN3-MGR-001", "VN3"],
    ["VND-KKM-001", "D1"],
    ["VNK-EGAISA15", "A15"],
    ["VNA-TV-A9N11", "A9"],
    ["VNA-TV-A9NA8", "A9"],
  ])("%s -> %s", (host, code) => {
    expect(hostnameStoreCode(host)).toBe(code);
  });

  it.each(["VNK-SEC-01", "VNK-TAM-003", "VNA-BUH-02", "VNK-SRV-SA11", "VNK-SRV-VIDEO16", "VNA-MGR-FASH01", "whatever", ""])(
    "leaves %s for a person",
    (host) => {
      expect(hostnameStoreCode(host)).toBeNull();
    },
  );
});

describe("computerTile", () => {
  it("splits the role from the rest of the name", () => {
    expect(computerTile("VNA-MGR-205")).toEqual({ type: "MGR", id: "205" });
    expect(computerTile("VNK-SEC-A2")).toEqual({ type: "SEC", id: "A2" });
    expect(computerTile("laptop").type).toBeNull();
  });
});

describe("computers on the map", () => {
  const index = buildStoreIndex([cash("VNA-KKM-201", "A2(200)", "DF"), cash("VNA-KKM-1501", "A15(100)", "DP")]);
  const ctx = (remote: Record<string, string> = {}) => ({ storeIndex: index, remoteLocation: (h: string) => remote[h] });

  it("puts a computer in the zone and under the label its store already has among the cash registers", () => {
    expect(placeComputer(pc("VNA-MGR-205"), ctx())).toMatchObject({ zone: { label: "Duty Free" }, label: "A2(200)" });
    expect(placeComputer(pc("VNA-MGR-1505"), ctx())).toMatchObject({ zone: { label: "Duty Paid" }, label: "A15(100)" });
  });

  it("trusts what the record says over what the name suggests", () => {
    // VNA-MGR-1602 reads as A16 by name, but the record puts it in A31
    expect(placeComputer(pc("VNA-MGR-1602", { location: "A31" }), ctx()).label).toBe("A31");
  });

  it("falls back to the location kept on the RustDesk entry", () => {
    expect(placeComputer(pc("VNK-SEC-33"), ctx({ "VNK-SEC-33": "A2(200)" })).label).toBe("A2(200)");
  });

  it("puts a store the cash registers do not know into 'Другие магазины'", () => {
    expect(placeComputer(pc("VNA-MGR-1602"), ctx())).toMatchObject({ zone: { label: "Другие магазины" }, label: "A16" });
  });

  it("groups office machines by role and keeps unplaced shop machines apart", () => {
    expect(placeComputer(pc("VNK-SEC-01"), ctx())).toMatchObject({ zone: { label: "Офис и служебные" }, label: "SEC" });
    expect(placeComputer(pc("VNA-BUH-02"), ctx())).toMatchObject({ zone: { label: "Магазин не определён" } });
  });

  it("builds zones in the reading order with per-zone counts", () => {
    const zones = computerView(
      [
        pc("VNK-SEC-01", { is_online: false }),
        pc("VNA-MGR-1505"),
        pc("VNA-MGR-205"),
        pc("VNA-MGR-206", { is_online: null }),
        pc("VNA-BUH-02"),
      ],
      ctx(),
    );

    expect(zones.map((z) => z.label)).toEqual(["Duty Free", "Duty Paid", "Офис и служебные", "Магазин не определён"]);
    expect(zones[0]).toMatchObject({ total: 2, online: 1, unknown: 1 });
    expect(zones[0].stores[0].tiles.map((t) => t.hostname)).toEqual(["VNA-MGR-205", "VNA-MGR-206"]);
    expect(zones[2]).toMatchObject({ total: 1, offline: 1 });
  });

  it("titles the tiles so a screen reader gets the state in words", () => {
    const [zone] = computerView([pc("VN3-MGR-001", { is_online: false })], ctx());

    expect(zone.stores[0].title).toBe("VN3 · Внуково 3");
    expect(zone.stores[0].tiles[0].aria).toBe("VN3-MGR-001, VN3 · Внуково 3, недоступен");
  });
});
