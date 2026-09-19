import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import type { Credential } from "../client";

const api = vi.hoisted(() => ({
  CREDENTIAL_CATEGORIES: [
    { value: "switch", label: "Свитч" },
    { value: "computer", label: "Компьютер" },
    { value: "server", label: "Сервер" },
    { value: "other", label: "Прочее" },
  ],
  getCredentials: vi.fn(),
  createCredential: vi.fn(),
  updateCredential: vi.fn(),
  deleteCredential: vi.fn(),
  revealCredential: vi.fn(),
  getRemoteDevices: vi.fn(),
}));

vi.mock("../client", () => api);

vi.mock("../hooks/useDebouncedValue", () => ({
  useDebouncedValue: (value: string) => value,
}));

vi.mock("../components/ConfirmDialog", () => ({
  useConfirm: () => () => Promise.resolve(true),
}));

import CredentialsPage from "./CredentialsPage";

function makeCredential(overrides: Partial<Credential> = {}): Credential {
  return {
    id: "cred-1",
    title: "Switch VNA core",
    category: "switch",
    username: "admin",
    has_secret: true,
    host: "10.10.1.1",
    location: "VNA",
    url: null,
    notes: null,
    tags: "core,mikrotik",
    secret_rotated_at: null,
    created_by_id: null,
    updated_by_id: null,
    created_at: "2026-09-01T00:00:00Z",
    updated_at: null,
    ...overrides,
  };
}

const renderPage = () =>
  render(
    <MemoryRouter>
      <QueryClientProvider client={new QueryClient()}>
        <CredentialsPage />
      </QueryClientProvider>
    </MemoryRouter>,
  );

beforeEach(() => {
  vi.clearAllMocks();
  api.getCredentials.mockResolvedValue({ data: [makeCredential()], count: 1 });
  api.getRemoteDevices.mockResolvedValue({ data: [], count: 0 });
});

describe("CredentialsPage", () => {
  it("lists vault entries and renders the generator", async () => {
    renderPage();
    expect(await screen.findByText("Switch VNA core")).toBeInTheDocument();
    expect(screen.getByText("Генератор паролей")).toBeInTheDocument();
    const pw = screen.getByTestId("generated-password").textContent ?? "";
    expect(pw.length).toBeGreaterThanOrEqual(8);
  });

  it("regenerates the preview without digits when the 0-9 class is unchecked", async () => {
    renderPage();
    await screen.findByText("Генератор паролей");

    fireEvent.click(screen.getByLabelText("0-9"));

    await waitFor(() => {
      const pw = screen.getByTestId("generated-password").textContent ?? "";
      expect(pw).not.toMatch(/[0-9]/);
      expect(pw.length).toBeGreaterThan(0);
    });
  });

  it("creates a credential from the form", async () => {
    api.createCredential.mockResolvedValue(makeCredential({ id: "cred-9", title: "New router" }));
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "Добавить" }));

    const dialog = await screen.findByRole("dialog", { name: "Новая запись" });
    fireEvent.change(within(dialog).getByLabelText("Название *"), { target: { value: "New router" } });
    fireEvent.change(within(dialog).getByLabelText("Пароль *"), { target: { value: "hunter2hunter2" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Сохранить" }));

    await waitFor(() =>
      expect(api.createCredential).toHaveBeenCalledWith(
        expect.objectContaining({ title: "New router", secret: "hunter2hunter2" }),
      ),
    );
  });

  it("keeps the form open when a text selection is dragged out onto the backdrop", async () => {
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Добавить" }));
    const dialog = await screen.findByRole("dialog", { name: "Новая запись" });
    const backdrop = dialog.parentElement as HTMLElement;

    // press inside the dialog, release over the backdrop: the browser still
    // dispatches a click on the backdrop, and it must not close the form
    fireEvent.mouseDown(within(dialog).getByLabelText("Название *"));
    fireEvent.mouseUp(backdrop);
    fireEvent.click(backdrop);
    expect(screen.getByRole("dialog", { name: "Новая запись" })).toBeInTheDocument();

    // a deliberate click on the backdrop still closes it
    fireEvent.mouseDown(backdrop);
    fireEvent.click(backdrop);
    expect(screen.queryByRole("dialog", { name: "Новая запись" })).not.toBeInTheDocument();
  });

  it("links a credential row to its device's fleet page", async () => {
    api.getCredentials.mockResolvedValue({
      data: [makeCredential({ category: "computer", host: "VNA-MGR-101" })],
      count: 1,
    });
    renderPage();

    const link = await screen.findByTitle("Открыть карточку устройства");
    expect(link).toHaveAttribute("href", "/computers?q=VNA-MGR-101&focus=VNA-MGR-101");
  });

  it("offers a RustDesk connect button when the host is a managed endpoint", async () => {
    api.getCredentials.mockResolvedValue({
      data: [makeCredential({ category: "computer", host: "VNA-MGR-101" })],
      count: 1,
    });
    api.getRemoteDevices.mockResolvedValue({
      data: [{ id: "dev-1", hostname: "VNA-MGR-101", rustdesk_id: "VNA_MGR_101" }],
      count: 1,
    });
    renderPage();

    const connect = await screen.findByTitle("Подключиться через RustDesk");
    expect(connect).toHaveAttribute("href", "rustdesk://connection/new/VNA_MGR_101");
  });

  it("does not offer device links for categories without a fleet section", async () => {
    api.getCredentials.mockResolvedValue({
      data: [makeCredential({ category: "server", host: "10.0.0.1" })],
      count: 1,
    });
    renderPage();

    await screen.findByText("10.0.0.1");
    expect(screen.queryByTitle("Открыть карточку устройства")).not.toBeInTheDocument();
  });
});
