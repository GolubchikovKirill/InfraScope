import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";

const api = vi.hoisted(() => ({
  getHonestSignTargets: vi.fn(),
  checkAllHonestSignTargets: vi.fn(),
  checkHonestSignTarget: vi.fn(),
  initializeHonestSignTarget: vi.fn(),
  updateHonestSignTargetIp: vi.fn(),
}));

vi.mock("../client", () => api);

const authState = vi.hoisted(() => ({
  user: { email: "admin@infrascope.dev", is_superuser: true } as { email: string; is_superuser: boolean } | null,
}));
vi.mock("../auth", () => ({
  useAuth: () => authState,
}));

import HonestSignPage from "./HonestSignPage";

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}><HonestSignPage /></QueryClientProvider>);
}

describe("HonestSignPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    authState.user = { email: "admin@infrascope.dev", is_superuser: true };
    api.getHonestSignTargets.mockResolvedValue({
      data: [{ host: "172.23.8.21", label: "A15", hostname: "VNK-KKM-1501", original_host: "172.23.8.21" }],
      count: 1,
      status_configured: true,
      initialization_configured: true,
    });
    api.checkAllHonestSignTargets.mockResolvedValue({
      data: [{ host: "172.23.8.21", label: "A15", hostname: "VNK-KKM-1501", original_host: "172.23.8.21", reachable: true, status: "not_initialized", version: "2.5.1", ready: false, message: "", checked_at: "2026-07-20T10:00:00Z" }],
      count: 1,
    });
    api.initializeHonestSignTarget.mockResolvedValue({
      host: "172.23.8.21",
      label: "A15",
      hostname: "VNK-KKM-1501",
      original_host: "172.23.8.21",
      initial_status: "not_initialized",
      final_status: "ready",
      result: "READY",
      message: "Статус после запроса: ready",
      checked_at: "2026-07-20T10:00:15Z",
    });
    api.updateHonestSignTargetIp.mockResolvedValue({
      host: "172.23.8.6",
      label: "A15",
      hostname: "VNK-KKM-1501",
      original_host: "172.23.8.21",
    });
  });

  it("requires explicit confirmation before initialization", async () => {
    renderPage();
    expect(await screen.findByText("172.23.8.21")).toBeInTheDocument();
    expect(screen.getByText("VNK-KKM-1501")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Активировать" }));
    expect(screen.getByText("Инициализировать Local Module?")).toBeInTheDocument();
    expect(api.initializeHonestSignTarget).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Подтвердить активацию" }));
    await waitFor(() => expect(api.initializeHonestSignTarget).toHaveBeenCalledTimes(1));
    expect(api.initializeHonestSignTarget.mock.calls[0]?.[0]).toBe("172.23.8.21");
  });

  it("hides activation for non-superusers but keeps status checks visible", async () => {
    authState.user = { email: "regular@infrascope.dev", is_superuser: false };
    renderPage();
    expect(await screen.findByText("172.23.8.21")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Активировать" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Проверить 172.23.8.21" })).toBeInTheDocument();
  });

  it("lets a superuser edit a target's IP", async () => {
    renderPage();
    expect(await screen.findByText("172.23.8.21")).toBeInTheDocument();

    fireEvent.click(screen.getByTitle("Изменить IP"));
    const input = screen.getByDisplayValue("172.23.8.21");
    fireEvent.change(input, { target: { value: "172.23.8.6" } });
    fireEvent.click(screen.getByTitle("Сохранить"));

    await waitFor(() => expect(api.updateHonestSignTargetIp).toHaveBeenCalledWith("172.23.8.21", "172.23.8.6"));
  });
});
