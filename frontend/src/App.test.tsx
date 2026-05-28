import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import type { ReactNode } from "react";

const api = vi.hoisted(() => ({
  pollAllPrinters: vi.fn(),
  pollAllMediaPlayers: vi.fn(),
  pollAllSwitches: vi.fn(),
  pollAllCashRegisters: vi.fn(),
  pollAllComputers: vi.fn(),
}));

vi.mock("./components/Layout", () => ({
  default: ({ children }: { children: ReactNode }) => <div>{children}</div>,
}));
vi.mock("./pages/Dashboard", () => ({ default: () => <div>DashboardPage</div> }));
vi.mock("./pages/MediaPlayersPage", () => ({ default: () => <div>MediaPlayersPage</div> }));
vi.mock("./pages/SwitchesPage", () => ({ default: () => <div>SwitchesPage</div> }));
vi.mock("./pages/Users", () => ({ default: () => <div>UsersPage</div> }));
vi.mock("./pages/Login", () => ({ default: () => <div>LoginPage</div> }));

const authState = {
  user: null as null | { is_superuser: boolean },
  isLoading: false,
};
vi.mock("./auth", () => ({
  useAuth: () => authState,
}));
vi.mock("./client", () => api);
vi.mock("./hooks/useRealtime", () => ({
  useRealtime: () => undefined,
}));

import App from "./App";

function renderWithProviders(initialPath: string) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialPath]}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("App routes", () => {
  it("redirects unauthenticated user to login", async () => {
    authState.user = null;
    renderWithProviders("/");
    expect(await screen.findByText("LoginPage")).toBeInTheDocument();
  });

  it("shows dashboard for authenticated user", async () => {
    authState.user = { is_superuser: true };
    renderWithProviders("/");
    expect(await screen.findByText("DashboardPage")).toBeInTheDocument();
  });

  it("shows 404 page for unknown route", async () => {
    authState.user = { is_superuser: true };
    renderWithProviders("/unknown-page");
    expect(await screen.findByText("Страница не найдена")).toBeInTheDocument();
  });

  it("does not run legacy global background poller", async () => {
    authState.user = { is_superuser: true };
    renderWithProviders("/");
    expect(await screen.findByText("DashboardPage")).toBeInTheDocument();

    expect(api.pollAllPrinters).not.toHaveBeenCalled();
    expect(api.pollAllMediaPlayers).not.toHaveBeenCalled();
    expect(api.pollAllSwitches).not.toHaveBeenCalled();
    expect(api.pollAllCashRegisters).not.toHaveBeenCalled();
    expect(api.pollAllComputers).not.toHaveBeenCalled();
  });
});

