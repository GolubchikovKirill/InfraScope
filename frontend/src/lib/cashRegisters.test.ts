import { describe, expect, it } from "vitest";
import type { CashRegister } from "../client";
import { cashState, groupByZoneAndStore, hasDrawerProblem, hasPiotProblem, isAttention, storeLabel, tileLabel } from "./cashRegisters";

const reg = (over: Partial<CashRegister> = {}): CashRegister =>
  ({
    id: "r-1",
    source_order: null,
    location_zone: "DF",
    kkm_number: "1",
    store_number: "A2(200)",
    hostname: "VNA-KKM-201",
    is_online: true,
    piot_status: null,
    cash_drawer: null,
    terminal_status: null,
    ...over,
  }) as CashRegister;

describe("storeLabel", () => {
  it("treats a Cyrillic look-alike letter and a stray space as the same store", () => {
    expect(storeLabel("А5 (203)")).toBe("A5(203)");
    expect(storeLabel("A5(203)")).toBe("A5(203)");
    expect(storeLabel("А23(105)")).toBe("A23(105)");
  });

  it("names a register with no store", () => {
    expect(storeLabel(null)).toBe("Без магазина");
    expect(storeLabel("  ")).toBe("Без магазина");
  });
});

describe("tileLabel", () => {
  it("shows the number at the end of the hostname", () => {
    expect(tileLabel("VNA-KKM-1506")).toBe("1506");
    expect(tileLabel("VN3-KKM-005")).toBe("005");
  });

  it("falls back to the tail of a hostname without digits", () => {
    expect(tileLabel("cassa-main")).toBe("-main");
    expect(tileLabel("")).toBe("—");
  });
});

describe("attention", () => {
  it("flags a terminal status, an outdated PIOT and a drawer that is not 'да'", () => {
    expect(isAttention(reg())).toBe(false);
    expect(isAttention(reg({ terminal_status: "нет связи" }))).toBe(true);
    expect(hasPiotProblem({ piot_status: "Не обновлен" })).toBe(true);
    expect(hasPiotProblem({ piot_status: "Обновлен" })).toBe(false);
    expect(hasDrawerProblem({ cash_drawer: "Нет" })).toBe(true);
    expect(hasDrawerProblem({ cash_drawer: "Да" })).toBe(false);
    expect(hasDrawerProblem({ cash_drawer: null })).toBe(false);
  });

  it("keeps availability and attention apart", () => {
    expect(cashState({ is_online: true })).toBe("online");
    expect(cashState({ is_online: false })).toBe("offline");
    expect(cashState({ is_online: null })).toBe("unknown");
  });
});

describe("groupByZoneAndStore", () => {
  const rows = [
    reg({ id: "1", hostname: "VNA-KKM-2002", store_number: "A2(200)" }),
    reg({ id: "2", hostname: "VNA-KKM-1001", store_number: "A10(208)" }),
    reg({ id: "3", hostname: "VNA-KKM-2001", store_number: "A2(200)", is_online: false }),
    reg({ id: "4", hostname: "VNA-KKM-1501", store_number: "А15(100)", location_zone: "DP" }),
    reg({ id: "5", hostname: "VNA-KKM-0001", store_number: null, location_zone: null, is_online: null }),
  ];

  it("orders zones Duty Free, Duty Paid, then the rest", () => {
    expect(groupByZoneAndStore(rows).map((z) => z.label)).toEqual(["Duty Free", "Duty Paid", "Без зоны"]);
  });

  it("sorts stores naturally and folds spelling variants into one store", () => {
    const df = groupByZoneAndStore(rows)[0];
    expect(df.stores.map((s) => s.label)).toEqual(["A2(200)", "A10(208)"]);
    expect(df.stores[0].rows.map((r) => r.hostname)).toEqual(["VNA-KKM-2001", "VNA-KKM-2002"]);
  });

  it("counts availability and remarks per zone", () => {
    const df = groupByZoneAndStore(rows)[0];
    expect(df).toMatchObject({ total: 3, online: 2, offline: 1, unknown: 0 });
    expect(groupByZoneAndStore(rows)[2]).toMatchObject({ total: 1, unknown: 1 });
  });
});
