import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";

const api = vi.hoisted(() => ({
  getHonestSignTargets: vi.fn(),
  checkAllHonestSignTargets: vi.fn(),
  checkHonestSignTarget: vi.fn(),
  initializeHonestSignTarget: vi.fn(),
}));

vi.mock("../client", () => api);

import HonestSignPage from "./HonestSignPage";

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}><HonestSignPage /></QueryClientProvider>);
}

describe("HonestSignPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.getHonestSignTargets.mockResolvedValue({
      data: [{ host: "172.23.8.21", label: "Касса" }],
      count: 1,
      status_configured: true,
      initialization_configured: true,
    });
    api.checkAllHonestSignTargets.mockResolvedValue({
      data: [{ host: "172.23.8.21", label: "Касса", reachable: true, status: "not_initialized", version: "2.5.1", ready: false, message: "", checked_at: "2026-07-20T10:00:00Z" }],
      count: 1,
    });
    api.initializeHonestSignTarget.mockResolvedValue({
      host: "172.23.8.21",
      label: "Касса",
      initial_status: "not_initialized",
      final_status: "ready",
      result: "READY",
      message: "Статус после запроса: ready",
      checked_at: "2026-07-20T10:00:15Z",
    });
  });

  it("requires explicit confirmation before initialization", async () => {
    renderPage();
    expect(await screen.findByText("172.23.8.21")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Активировать" }));
    expect(screen.getByText("Инициализировать Local Module?")).toBeInTheDocument();
    expect(api.initializeHonestSignTarget).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Подтвердить активацию" }));
    await waitFor(() => expect(api.initializeHonestSignTarget).toHaveBeenCalledTimes(1));
    expect(api.initializeHonestSignTarget.mock.calls[0]?.[0]).toBe("172.23.8.21");
  });
});
