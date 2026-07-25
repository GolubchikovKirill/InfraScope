import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import type { ReactNode } from "react";

const authState = {
  user: null as null | { email: string; full_name: string | null; is_superuser: boolean },
  logout: vi.fn(),
};

vi.mock("../auth", () => ({
  useAuth: () => authState,
}));

import Layout from "./Layout";

function renderLayout(path = "/") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Layout>
        <div>Page content</div>
      </Layout>
    </MemoryRouter>,
  );
}

describe("Layout account block", () => {
  beforeEach(() => {
    authState.logout.mockReset();
    localStorage.clear();
    document.documentElement.removeAttribute("data-theme");
  });

  it("shows full name and email when full name is present", () => {
    authState.user = {
      email: "admin@infrascope.dev",
      full_name: "Кирилл Голубчиков",
      is_superuser: true,
    };

    renderLayout("/");

    expect(screen.getByText("Кирилл Голубчиков")).toBeInTheDocument();
    expect(screen.getByText("admin@infrascope.dev")).toBeInTheDocument();
    expect(screen.getByText("Сессия активна")).toBeInTheDocument();
  });

  it("falls back to email and role when full name is empty", () => {
    authState.user = {
      email: "ops@infrascope.dev",
      full_name: "   ",
      is_superuser: false,
    };

    renderLayout("/settings");

    expect(screen.getByText("ops@infrascope.dev")).toBeInTheDocument();
    expect(screen.getByText("Пользователь")).toBeInTheDocument();
  });

  it("calls logout action from sidebar button", () => {
    authState.user = {
      email: "admin@infrascope.dev",
      full_name: "Admin",
      is_superuser: true,
    };

    renderLayout("/");
    fireEvent.click(screen.getByRole("button", { name: /Выход/i }));

    expect(authState.logout).toHaveBeenCalledTimes(1);
  });

  it("toggles theme and persists mode", () => {
    authState.user = {
      email: "admin@infrascope.dev",
      full_name: "Admin",
      is_superuser: true,
    };

    renderLayout("/");
    const toggle = screen.getByTitle("Включить тёмную тему");
    fireEvent.click(toggle);

    expect(localStorage.getItem("infrascope:theme-mode")).toBe("dark");
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
  });

  it("shows Honest Sign to any authenticated user", () => {
    authState.user = {
      email: "any.user@infrascope.dev",
      full_name: "Обычный пользователь",
      is_superuser: false,
    };
    renderLayout("/");
    expect(screen.getAllByRole("link", { name: "Честный знак" }).length).toBeGreaterThan(0);
  });
});
