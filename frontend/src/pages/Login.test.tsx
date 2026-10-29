import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { AxiosError, AxiosHeaders } from "axios";
import { vi } from "vitest";

const login = vi.fn();

vi.mock("../auth", () => ({
  useAuth: () => ({ user: null, login }),
}));

import Login from "./Login";

function apiError(status: number, data: unknown) {
  const config = { headers: new AxiosHeaders() };
  return new AxiosError("Request failed", "ERR_BAD_REQUEST", config, null, {
    status,
    statusText: "",
    data,
    headers: {},
    config,
  });
}

async function submit() {
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
}

describe("Login page", () => {
  it("shows auth error on wrong credentials", async () => {
    login.mockRejectedValueOnce(apiError(400, { detail: "Incorrect email or password" }));
    await submit();
    await waitFor(() => {
      expect(screen.getByText("Неверный email или пароль")).toBeInTheDocument();
    });
  });

  it("does not blame the password when the server rejects the request itself", async () => {
    // TrustedHostMiddleware answers a wrong Host with a plain-text 400
    login.mockRejectedValueOnce(apiError(400, "Invalid host header"));
    await submit();
    await waitFor(() => {
      expect(screen.getByText("Ошибка сервера при входе (HTTP 400)")).toBeInTheDocument();
    });
  });

  it("reports an unreachable server", async () => {
    login.mockRejectedValueOnce(new Error("Network Error"));
    await submit();
    await waitFor(() => {
      expect(screen.getByText("Сервер недоступен, вход не выполнен")).toBeInTheDocument();
    });
  });
});
