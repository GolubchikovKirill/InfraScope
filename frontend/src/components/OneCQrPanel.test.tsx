import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { vi } from "vitest";

const api = vi.hoisted(() => ({
  exportQrGenerator: vi.fn(),
}));

vi.mock("../client", () => ({
  exportQrGenerator: api.exportQrGenerator,
}));

import OneCQrPanel from "./OneCQrPanel";

function renderPanel() {
  const queryClient = new QueryClient({
    defaultOptions: {
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <OneCQrPanel />
    </QueryClientProvider>,
  );
}

describe("OneCQrPanel", () => {
  it("submits normalized payload and shows success state", async () => {
    api.exportQrGenerator.mockResolvedValue(new Blob(["zip-content"], { type: "application/zip" }));
    const createUrl = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:test");
    const revokeUrl = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});

    renderPanel();

    fireEvent.change(screen.getByPlaceholderText("4007"), {
      target: { value: " 4011 " },
    });
    fireEvent.change(screen.getByPlaceholderText("Иванов, Петров"), {
      target: { value: "  Иванов, Петров  " },
    });
    fireEvent.click(screen.getByLabelText("Добавлять логин/ID мелким текстом"));
    fireEvent.click(screen.getByRole("button", { name: "Сформировать и скачать ZIP" }));

    await waitFor(() => {
      expect(api.exportQrGenerator).toHaveBeenCalled();
      expect(api.exportQrGenerator.mock.calls[0]?.[0]).toEqual({
        db_mode: "duty_free",
        airport_code: "4011",
        surnames: "Иванов, Петров",
        add_login: true,
      });
    });
    expect(await screen.findByText("Архив сформирован и скачан.")).toBeInTheDocument();

    createUrl.mockRestore();
    revokeUrl.mockRestore();
    clickSpy.mockRestore();
  });

  it("resets form fields to defaults", () => {
    renderPanel();

    fireEvent.change(screen.getByPlaceholderText("4007"), {
      target: { value: "4999" },
    });
    fireEvent.change(screen.getByPlaceholderText("Иванов, Петров"), {
      target: { value: "Петров" },
    });
    fireEvent.click(screen.getByLabelText("Добавлять логин/ID мелким текстом"));
    fireEvent.click(screen.getByRole("button", { name: "Сбросить" }));

    expect(screen.getByPlaceholderText("4007")).toHaveValue("4007");
    expect(screen.getByPlaceholderText("Иванов, Петров")).toHaveValue("");
    expect(screen.getByLabelText("Добавлять логин/ID мелким текстом")).not.toBeChecked();
  });
});
