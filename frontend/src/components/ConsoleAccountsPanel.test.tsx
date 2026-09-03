import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { vi } from "vitest";

const api = vi.hoisted(() => ({
  getConsoleAccounts: vi.fn(),
  getAddressBookStatus: vi.fn(),
  createConsoleAccount: vi.fn(),
  resetConsoleAccountPassword: vi.fn(),
  setConsoleAccountActive: vi.fn(),
  syncConsoleAccounts: vi.fn(),
}));

vi.mock("../client", () => api);

import ConsoleAccountsPanel from "./ConsoleAccountsPanel";
import { ConfirmProvider } from "./ConfirmDialog";

const renderPanel = (isSuperuser = true) =>
  render(
    <QueryClientProvider client={new QueryClient()}>
      <ConfirmProvider>
        <ConsoleAccountsPanel isSuperuser={isSuperuser} />
      </ConfirmProvider>
    </QueryClientProvider>,
  );

const account = {
  id: "acc-1",
  username: "ivanov",
  console_user_id: 7,
  display_name: "Иван Иванов",
  email: null,
  is_admin: false,
  infrascope_user_id: null,
  active: true,
  book_shared: true,
  last_synced_at: "2026-09-02T10:00:00Z",
  created_at: "2026-09-01T00:00:00Z",
};

beforeEach(() => {
  // hoisted mocks are shared across every `it()` in this file and vitest does
  // not clear call history between tests on its own (no clearMocks in the
  // vite config) - without this, a later `toHaveBeenCalledWith`/`.not.toHaveBeenCalled()`
  // sees calls left over from an earlier test.
  vi.clearAllMocks();
  api.getAddressBookStatus.mockResolvedValue({
    name: "InfraScope",
    collection_id: 100,
    owner_user_id: 1,
    entries: 42,
    shared_with_group: "InfraScope Admins",
    accounts: 3,
  });
});

describe("ConsoleAccountsPanel", () => {
  it("lists accounts and the shared-book summary", async () => {
    api.getConsoleAccounts.mockResolvedValue({ data: [account], count: 1 });
    renderPanel();

    expect(await screen.findByText("ivanov")).toBeInTheDocument();
    expect(screen.getByText("Иван Иванов")).toBeInTheDocument();
    expect(await screen.findByText("42")).toBeInTheDocument();
    expect(screen.getByText("InfraScope Admins")).toBeInTheDocument();
  });

  it("creates an account and shows the one-time password", async () => {
    api.getConsoleAccounts.mockResolvedValue({ data: [], count: 0 });
    api.createConsoleAccount.mockResolvedValue({
      account: { ...account, id: "acc-2", username: "petrov" },
      password: "aB3xY9Qw2Kmn",
      note: "Пароль показывается один раз и не хранится в InfraScope.",
    });
    renderPanel();

    fireEvent.click(await screen.findByText("Добавить"));
    fireEvent.change(screen.getByPlaceholderText("ivanov"), { target: { value: "petrov" } });
    fireEvent.click(screen.getByText("Создать"));

    await waitFor(() => {
      expect(api.createConsoleAccount).toHaveBeenCalledWith(
        expect.objectContaining({ username: "petrov", is_admin: false }),
      );
    });
    expect(await screen.findByText("aB3xY9Qw2Kmn")).toBeInTheDocument();
    expect(screen.getByText(/показывается один раз/)).toBeInTheDocument();
  });

  it("blocks creation until the username matches the allowed pattern", async () => {
    api.getConsoleAccounts.mockResolvedValue({ data: [], count: 0 });
    renderPanel();

    fireEvent.click(await screen.findByText("Добавить"));
    fireEvent.change(screen.getByPlaceholderText("ivanov"), { target: { value: "a" } });
    expect(screen.getByText("Создать")).toBeDisabled();
    expect(api.createConsoleAccount).not.toHaveBeenCalled();
  });

  it("resets a password and shows it once", async () => {
    api.getConsoleAccounts.mockResolvedValue({ data: [account], count: 1 });
    api.resetConsoleAccountPassword.mockResolvedValue({
      account,
      password: "freshSecret123",
      note: "Пароль показывается один раз и не хранится в InfraScope.",
    });
    renderPanel();

    await screen.findByText("ivanov");
    fireEvent.click(screen.getByTitle("Сбросить пароль"));

    await waitFor(() => expect(api.resetConsoleAccountPassword).toHaveBeenCalledWith("acc-1"));
    expect(await screen.findByText("freshSecret123")).toBeInTheDocument();
  });

  it("asks for confirmation before disabling an active account", async () => {
    api.getConsoleAccounts.mockResolvedValue({ data: [account], count: 1 });
    api.setConsoleAccountActive.mockResolvedValue({ ...account, active: false });
    renderPanel();

    await screen.findByText("ivanov");
    fireEvent.click(screen.getByTitle("Отключить"));

    const dialogMessage = await screen.findByText(/Отключить учётку/);
    expect(api.setConsoleAccountActive).not.toHaveBeenCalled();

    // the row's own icon button and the dialog's confirm button share the
    // same accessible name ("Отключить") - scope to the dialog panel so the
    // click lands on the confirm button, not the (still-mounted) row button
    const dialog = dialogMessage.closest(".app-panel") as HTMLElement;
    fireEvent.click(within(dialog).getByRole("button", { name: "Отключить" }));
    await waitFor(() => expect(api.setConsoleAccountActive).toHaveBeenCalledWith("acc-1", false));
  });

  it("hides management actions for non-superusers", async () => {
    api.getConsoleAccounts.mockResolvedValue({ data: [account], count: 1 });
    renderPanel(false);

    await screen.findByText("ivanov");
    expect(screen.queryByText("Добавить")).not.toBeInTheDocument();
    expect(screen.queryByTitle("Сбросить пароль")).not.toBeInTheDocument();
  });
});
