import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";

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

  it("folds the sidebar to an icon rail and back", () => {
    authState.user = {
      email: "admin@infrascope.dev",
      full_name: "Admin",
      is_superuser: true,
    };

    renderLayout("/");

    expect(screen.queryByTitle("Развернуть меню")).not.toBeInTheDocument();

    fireEvent.click(screen.getByTitle("Свернуть меню"));
    expect(localStorage.getItem("infrascope_sidebar_hidden")).toBe("1");

    // Navigation stays reachable on the rail, named for screen readers
    const rail = screen.getByRole("complementary");
    expect(within(rail).getByRole("link", { name: "Кассы" })).toHaveAttribute("href", "/cash-registers");
    expect(within(rail).queryByText("Кассы")).not.toBeInTheDocument();

    // ...and hovering an icon names it
    fireEvent.mouseEnter(within(rail).getByRole("link", { name: "Кассы" }));
    expect(screen.getByRole("tooltip")).toHaveTextContent("Кассы");

    fireEvent.click(screen.getByTitle("Развернуть меню"));
    expect(localStorage.getItem("infrascope_sidebar_hidden")).toBe("0");
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
    expect(within(rail).getByText("Кассы")).toBeInTheDocument();
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

describe("Layout navigation", () => {
  beforeEach(() => {
    localStorage.clear();
    authState.user = { email: "ops@infrascope.dev", full_name: "Ops", is_superuser: false };
  });

  it("keeps Honest Sign outside the collapsible Equipment group", () => {
    renderLayout("/");

    // collapse the group: its own items disappear, Honest Sign stays
    fireEvent.click(screen.getAllByRole("button", { name: /Оборудование/ })[0]); // desktop and mobile toggles share one state

    expect(screen.queryAllByRole("link", { name: "Принтеры" })).toHaveLength(0);
    expect(screen.getAllByRole("link", { name: "Честный знак" }).length).toBeGreaterThan(0);
    for (const link of screen.getAllByRole("link", { name: "Честный знак" })) {
      expect(link).toHaveAttribute("href", "/honest-sign");
    }
  });

  it("lists the Screens tab inside the Equipment group", () => {
    renderLayout("/");

    for (const link of screen.getAllByRole("link", { name: "Экраны" })) expect(link).toHaveAttribute("href", "/screens");
    // it belongs to the group: collapsing Equipment takes it away with the rest
    fireEvent.click(screen.getAllByRole("button", { name: /Оборудование/ })[0]);
    expect(screen.queryAllByRole("link", { name: "Экраны" })).toHaveLength(0);
  });

  it("has no network search entry", () => {
    renderLayout("/");

    expect(screen.queryByRole("link", { name: "Поиск в сети" })).not.toBeInTheDocument();
  });
});
