import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";

const api = vi.hoisted(() => ({
  getDeployCommand: vi.fn(),
}));

vi.mock("../client", () => api);

import DeployCommandModal from "./DeployCommandModal";

const renderModal = (open: boolean) =>
  render(
    <QueryClientProvider client={new QueryClient()}>
      <DeployCommandModal open={open} onClose={vi.fn()} />
    </QueryClientProvider>,
  );

describe("DeployCommandModal", () => {
  it("renders nothing while closed and does not fetch", () => {
    const { container } = renderModal(false);
    expect(container).toBeEmptyDOMElement();
    expect(api.getDeployCommand).not.toHaveBeenCalled();
  });

  it("warns when the server has no deploy token configured", async () => {
    api.getDeployCommand.mockResolvedValue({
      command: "",
      bootstrap_url: "http://10.10.99.24:8000/api/v1/remote-access/deploy/bootstrap.ps1",
      installer_filename: "rustdesk-1.4.9-x86_64.msi",
      installer_version: "1.4.9",
      configured: false,
    });
    renderModal(true);
    expect(await screen.findByText(/не настроено на сервере/)).toBeInTheDocument();
    expect(screen.queryByText("Скопировать команду")).not.toBeInTheDocument();
  });

  it("shows the command and copies it on click", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });

    api.getDeployCommand.mockResolvedValue({
      command: "powershell.exe -NoProfile -Command \"iex ...\"",
      bootstrap_url: "http://10.10.99.24:8000/api/v1/remote-access/deploy/bootstrap.ps1",
      installer_filename: "rustdesk-1.4.9-x86_64.msi",
      installer_version: "1.4.9",
      configured: true,
    });
    renderModal(true);

    expect(await screen.findByText(/powershell.exe/)).toBeInTheDocument();
    fireEvent.click(screen.getByText("Скопировать команду"));
    await waitFor(() => {
      expect(writeText).toHaveBeenCalledWith('powershell.exe -NoProfile -Command "iex ..."');
    });
  });

  it("always offers the reboot-free push command for Windows 7 and copies it", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    api.getDeployCommand.mockResolvedValue({
      command: "",
      bootstrap_url: "",
      installer_filename: "rustdesk-1.4.9-x86_64.msi",
      installer_version: "1.4.9",
      configured: false,
    });
    renderModal(true);

    expect(await screen.findByText(/Windows 7 и раскатка без перезагрузки/)).toBeInTheDocument();
    expect(screen.getByText(/ничего не перезагружает/)).toBeInTheDocument();
    fireEvent.click(screen.getByText("Скопировать push-команду"));
    await waitFor(() => {
      expect(writeText).toHaveBeenCalledWith(expect.stringContaining("Push-RustDesk.ps1 -ComputerName"));
    });
  });
});
