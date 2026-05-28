import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";

vi.mock("../auth", () => ({
  useAuth: () => ({
    user: null,
    login: vi.fn(async () => {
      throw new Error("bad creds");
    }),
  }),
}));

import Login from "./Login";

describe("Login page", () => {
  it("shows auth error on failed login", async () => {
    render(
      <MemoryRouter>
        <Login />
      </MemoryRouter>,
    );

    const emailInput = screen.getByPlaceholderText("admin@infrascope.dev");
    const passwordInput = document.querySelector("input[type='password']") as HTMLInputElement;
    fireEvent.change(emailInput, { target: { value: "admin@example.com" } });
    fireEvent.change(passwordInput, { target: { value: "wrong" } });
    fireEvent.click(screen.getByRole("button", { name: "Войти" }));

    await waitFor(() => {
      expect(screen.getByText("Неверный email или пароль")).toBeInTheDocument();
    });
  });
});

