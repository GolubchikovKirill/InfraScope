import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";

vi.mock("./client", () => ({
  login: vi.fn(async () => ({ access_token: "token-123" })),
  logout: vi.fn(async () => ({})),
  getMe: vi.fn(async () => ({
    id: "u1",
    email: "admin@example.com",
    full_name: "Admin",
    is_superuser: true,
  })),
}));

import { AuthProvider, useAuth } from "./auth";

function Probe() {
  const { user, login, logout, isLoading } = useAuth();
  return (
    <div>
      <div data-testid="loading">{String(isLoading)}</div>
      <div data-testid="email">{user?.email ?? "none"}</div>
      <button onClick={() => login("admin@example.com", "Pass1234")}>login</button>
      <button onClick={logout}>logout</button>
    </div>
  );
}

describe("AuthProvider", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("logs in and populates current user", async () => {
    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );

    fireEvent.click(screen.getByText("login"));

    await waitFor(() => {
      expect(screen.getByTestId("email")).toHaveTextContent("admin@example.com");
    });
    expect(localStorage.getItem("access_token")).toBe("token-123");
  });

  it("logs out and clears token", async () => {
    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );

    fireEvent.click(screen.getByText("logout"));

    await waitFor(() => {
      expect(screen.getByTestId("email")).toHaveTextContent("none");
    });
    expect(localStorage.getItem("access_token")).toBeNull();
  });
});

