import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import type { CashRegister } from "../../client";

vi.mock("../RemoteAccessButtons", () => ({
  default: ({ hostname }: { hostname: string }) => <button type="button">Подключиться к {hostname}</button>,
}));

import CashRegisterDrawer from "./CashRegisterDrawer";
import CashRegisterMap from "./CashRegisterMap";

const reg = (over: Partial<CashRegister>): CashRegister =>
  ({
    id: "r-1",
    source_order: null,
    location_zone: "DF",
    kkm_number: "64698 (1506)",
    store_number: "A2(200)",
    hostname: "VNA-KKM-201",
    windows_version: "10",
    piot_status: "Обновлен",
    cash_drawer: "Да",
    terminal_status: null,
    second_screen: null,
    comment: null,
    reachability_reason: null,
    last_polled_at: null,
    is_online: true,
    ...over,
  }) as CashRegister;

const rows = [
  reg({ id: "1", hostname: "VNA-KKM-201" }),
  reg({ id: "2", hostname: "VNA-KKM-202", is_online: false, reachability_reason: "no_response" }),
  reg({ id: "3", hostname: "VNA-KKM-1501", store_number: "A15(100)", location_zone: "DP", terminal_status: "нет связи" }),
  reg({ id: "4", hostname: "VNA-KKM-1502", store_number: "A15(100)", location_zone: "DP", is_online: null }),
];

const renderMap = (onSelect = vi.fn()) => {
  render(
    <MemoryRouter>
      <CashRegisterMap rows={rows} isLoading={false} onSelect={onSelect} />
    </MemoryRouter>,
  );
  return onSelect;
};

describe("CashRegisterMap", () => {
  it("groups the registers by zone and store with per-store availability", () => {
    renderMap();

    const df = screen.getByTestId("zone-DF");
    expect(within(df).getByText("Duty Free")).toBeInTheDocument();
    expect(within(df).getByText(/2 касс · 1 на связи · 1 недоступны/)).toBeInTheDocument();
    expect(within(screen.getByTestId("store-DF:A2(200)")).getByText("1/2")).toBeInTheDocument();
    expect(within(screen.getByTestId("zone-DP")).getByText("Duty Paid")).toBeInTheDocument();
  });

  it("labels each tile with the number, and says the state in words, not only by colour", () => {
    renderMap();

    expect(screen.getByRole("button", { name: /VNA-KKM-202, A2\(200\), недоступна/ })).toHaveTextContent("202");
    expect(screen.getByRole("button", { name: /VNA-KKM-1501, A15\(100\), на связи, есть замечание/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /VNA-KKM-1502, A15\(100\), нет данных/ })).toBeInTheDocument();
  });

  it("selects a register when its tile is clicked", () => {
    const onSelect = renderMap();

    fireEvent.click(screen.getByRole("button", { name: /VNA-KKM-202/ }));

    expect(onSelect).toHaveBeenCalledWith("2");
  });

  it("narrows by a search text and by 'only with remarks'", () => {
    renderMap();

    fireEvent.change(screen.getByPlaceholderText("Касса или магазин"), { target: { value: "a15" } });
    expect(screen.queryByTestId("zone-DF")).not.toBeInTheDocument();
    expect(screen.getByTestId("zone-DP")).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText("Касса или магазин"), { target: { value: "" } });
    fireEvent.click(screen.getByLabelText("Только с замечаниями"));
    // healthy online registers drop out; offline, unknown and remarked ones stay
    expect(screen.queryByRole("button", { name: /VNA-KKM-201,/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /VNA-KKM-202/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /VNA-KKM-1501/ })).toBeInTheDocument();
  });

  it("says so when nothing matches", () => {
    renderMap();

    fireEvent.change(screen.getByPlaceholderText("Касса или магазин"), { target: { value: "zzz" } });

    expect(screen.getByText("По этому запросу касс нет.")).toBeInTheDocument();
  });
});

describe("CashRegisterDrawer", () => {
  const renderDrawer = (register: CashRegister, isSuperuser = true, onClose = vi.fn()) => {
    render(
      <MemoryRouter>
        <CashRegisterDrawer register={register} isSuperuser={isSuperuser} onClose={onClose} />
      </MemoryRouter>,
    );
    return onClose;
  };

  it("offers the connection and the quick facts, and links to the full Cash registers page", () => {
    renderDrawer(rows[2]);

    const dialog = screen.getByRole("dialog", { name: "Касса VNA-KKM-1501" });
    expect(within(dialog).getByRole("button", { name: "Подключиться к VNA-KKM-1501" })).toBeInTheDocument();
    expect(within(dialog).getByText("нет связи")).toBeInTheDocument(); // terminal status
    expect(within(dialog).getByRole("link", { name: /Все данные и правка в «Кассы»/ })).toHaveAttribute(
      "href",
      "/cash-registers?q=VNA-KKM-1501&focus=VNA-KKM-1501",
    );
  });

  it("explains why an offline register does not answer", () => {
    renderDrawer(rows[1]);

    expect(screen.getByText("Недоступна")).toBeInTheDocument();
    expect(screen.getByText("Нет ответа")).toBeInTheDocument();
  });

  it("shows the passwords link to a superuser only", () => {
    const { unmount } = render(
      <MemoryRouter>
        <CashRegisterDrawer register={rows[0]} isSuperuser={true} onClose={vi.fn()} />
      </MemoryRouter>,
    );
    expect(screen.getByRole("link", { name: "Пароли" })).toBeInTheDocument();
    unmount();

    renderDrawer(rows[0], false);
    expect(screen.queryByRole("link", { name: "Пароли" })).not.toBeInTheDocument();
  });

  it("closes on Escape and on the close button, but not on a click inside the panel", () => {
    const onClose = renderDrawer(rows[0]);

    fireEvent.click(screen.getByRole("dialog"));
    expect(onClose).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Закрыть" }));
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it("does not close when a selection drag ends on the backdrop", () => {
    const onClose = renderDrawer(rows[0]);
    const backdrop = screen.getByRole("dialog").parentElement as HTMLElement;

    fireEvent.mouseDown(screen.getByRole("dialog"));
    fireEvent.click(backdrop);
    expect(onClose).not.toHaveBeenCalled();

    fireEvent.mouseDown(backdrop);
    fireEvent.click(backdrop);
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
