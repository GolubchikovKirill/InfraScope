import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { vi } from "vitest";
import type { StaleComputer } from "../client";

const api = vi.hoisted(() => ({ getStaleComputers: vi.fn(), deleteComputer: vi.fn() }));
vi.mock("../client", () => api);

const confirmMock = vi.hoisted(() => vi.fn());
vi.mock("./ConfirmDialog", () => ({ useConfirm: () => confirmMock }));

const toast = vi.hoisted(() => vi.fn());
vi.mock("../lib/toastBus", () => ({ showToast: toast }));

import StaleComputersModal from "./StaleComputersModal";

const stale = (hostname: string, over: Partial<StaleComputer> = {}): StaleComputer => ({
  id: hostname,
  hostname,
  location: null,
  comment: null,
  is_online: false,
  last_polled_at: null,
  created_at: "2026-09-02T00:00:00Z",
  reason: "нет в консоли RustDesk и не отвечает на пинг",
  laptop_like: false,
  in_remote_access: false,
  ...over,
});

const renderModal = (onClose = vi.fn()) => {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <StaleComputersModal onClose={onClose} />
    </QueryClientProvider>,
  );
  return onClose;
};

const list = (data: StaleComputer[], console_reachable = true) => ({ console_reachable, count: data.length, data });

beforeEach(() => {
  vi.clearAllMocks();
  confirmMock.mockResolvedValue(true);
  api.deleteComputer.mockResolvedValue(undefined);
  api.getStaleComputers.mockResolvedValue(list([stale("VNK-SEC-07", { in_remote_access: true }), stale("VNA-MGR-202"), stale("VNK-TAM-NB01", { laptop_like: true })]));
});

describe("StaleComputersModal", () => {
  it("preselects everything except laptops and says which entries are in remote access", async () => {
    renderModal();

    expect(await screen.findByRole("checkbox", { name: "Удалить VNK-SEC-07" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Удалить VNA-MGR-202" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Удалить VNK-TAM-NB01" })).not.toBeChecked();
    expect(screen.getByText("ноутбук")).toBeInTheDocument();
    expect(screen.getByText("в удалённом доступе")).toBeInTheDocument();
    expect(screen.getByText("Отмечено 2 из 3")).toBeInTheDocument();
  });

  it("asks before deleting and then removes exactly the ticked computers", async () => {
    renderModal();
    await screen.findByRole("checkbox", { name: "Удалить VNK-SEC-07" });
    fireEvent.click(screen.getByRole("checkbox", { name: "Удалить VNK-TAM-NB01" })); // also tick the laptop
    fireEvent.click(screen.getByRole("checkbox", { name: "Удалить VNA-MGR-202" })); // untick one

    fireEvent.click(screen.getByRole("button", { name: /Удалить выбранные \(2\)/ }));

    await waitFor(() => expect(confirmMock).toHaveBeenCalledTimes(1));
    expect(confirmMock.mock.calls[0][0]).toMatch(/Удалить компьютеров: 2\?.*1 из них также из удалённого доступа/);
    await waitFor(() => expect(api.deleteComputer).toHaveBeenCalledTimes(2));
    expect(api.deleteComputer.mock.calls.map((c) => c[0]).sort()).toEqual(["VNK-SEC-07", "VNK-TAM-NB01"]);
    expect(toast).toHaveBeenCalledWith("Удалено компьютеров: 2", "success");
  });

  it("deletes nothing when the confirmation is declined", async () => {
    confirmMock.mockResolvedValue(false);
    renderModal();
    await screen.findByRole("checkbox", { name: "Удалить VNA-MGR-202" });

    fireEvent.click(screen.getByRole("button", { name: /Удалить выбранные/ }));

    await waitFor(() => expect(confirmMock).toHaveBeenCalled());
    expect(api.deleteComputer).not.toHaveBeenCalled();
  });

  it("reports the ones it could not delete and carries on with the rest", async () => {
    api.deleteComputer.mockImplementation(async (id: string) => {
      if (id === "VNK-SEC-07") throw new Error("boom");
    });
    renderModal();
    await screen.findByRole("checkbox", { name: "Удалить VNK-SEC-07" });

    fireEvent.click(screen.getByRole("button", { name: /Удалить выбранные/ }));

    await waitFor(() => expect(toast).toHaveBeenCalledWith("Не удалось удалить: VNK-SEC-07", "error"));
    expect(toast).toHaveBeenCalledWith("Удалено компьютеров: 1", "success");
  });

  it("selects all but laptops or nothing on request", async () => {
    renderModal();
    await screen.findByText("Отмечено 2 из 3");

    fireEvent.click(screen.getByRole("button", { name: "Снять всё" }));
    expect(screen.getByText("Отмечено 0 из 3")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Удалить выбранные \(0\)/ })).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Все, кроме ноутбуков" }));
    expect(screen.getByText("Отмечено 2 из 3")).toBeInTheDocument();
  });

  it("offers nothing to delete while the console cannot be read", async () => {
    api.getStaleComputers.mockResolvedValue(list([], false));
    renderModal();

    expect(await screen.findByText(/судить о неактуальности нельзя/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Удалить выбранные \(0\)/ })).toBeDisabled();
  });

  it("says so when nothing is stale", async () => {
    api.getStaleComputers.mockResolvedValue(list([]));
    renderModal();

    expect(await screen.findByText(/Неактуальных компьютеров нет/)).toBeInTheDocument();
  });

  it("closes from either close button and on Escape", async () => {
    const onClose = renderModal();
    await screen.findByRole("dialog", { name: "Неактуальные компьютеры" });

    for (const button of within(screen.getByRole("dialog")).getAllByRole("button", { name: "Закрыть" })) fireEvent.click(button);
    fireEvent.keyDown(document, { key: "Escape" });

    expect(onClose).toHaveBeenCalledTimes(3);
  });
});
