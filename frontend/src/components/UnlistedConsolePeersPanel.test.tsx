import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";

const api = vi.hoisted(() => ({
  getUnlistedConsolePeers: vi.fn(),
  adoptConsolePeer: vi.fn(),
  dismissConsolePeer: vi.fn(),
}));

vi.mock("../client", () => api);

import UnlistedConsolePeersPanel from "./UnlistedConsolePeersPanel";

const renderPanel = (isSuperuser = true) =>
  render(
    <QueryClientProvider client={new QueryClient()}>
      <UnlistedConsolePeersPanel isSuperuser={isSuperuser} />
    </QueryClientProvider>,
  );

const peer = (over: Record<string, unknown> = {}) => ({
  hostname: "vnk-itd-sa03",
  rustdesk_id: "VNKITDSA03",
  os: "windows",
  version: "1.4.9",
  username: "ivanov",
  online: true,
  last_online: "2026-09-19T10:00:00Z",
  suggested_profile: "admin",
  ...over,
});

const response = (over: Record<string, unknown> = {}) => ({
  data: [peer(), peer({ hostname: "vna-mgr-101", suggested_profile: "client", online: false, username: null })],
  count: 2,
  nameless_peers: 0,
  console_reachable: true,
  ...over,
});

beforeEach(() => {
  vi.clearAllMocks();
  api.getUnlistedConsolePeers.mockResolvedValue(response());
  api.adoptConsolePeer.mockResolvedValue({ hostname: "vnk-itd-sa03" });
  api.dismissConsolePeer.mockResolvedValue({ message: "vnk-itd-sa03: скрыто из предложений" });
});

describe("UnlistedConsolePeersPanel", () => {
  it("lists the console machines that are not tracked", async () => {
    renderPanel();

    expect(await screen.findByText("vnk-itd-sa03")).toBeInTheDocument();
    expect(screen.getByText("vna-mgr-101")).toBeInTheDocument();
    expect(screen.getByText(/есть машины, которых нет в списке/)).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
  });

  it("preselects the suggested profile per machine", async () => {
    renderPanel();
    await screen.findByText("vnk-itd-sa03");

    expect(screen.getByLabelText("Профиль для vnk-itd-sa03")).toHaveValue("admin");
    expect(screen.getByLabelText("Профиль для vna-mgr-101")).toHaveValue("client");
  });

  it("adopts a machine with the chosen profile", async () => {
    renderPanel();
    await screen.findByText("vnk-itd-sa03");

    fireEvent.change(screen.getByLabelText("Профиль для vnk-itd-sa03"), { target: { value: "client" } });
    fireEvent.click(screen.getAllByRole("button", { name: /Взять в управление/ })[0]);

    await waitFor(() =>
      expect(api.adoptConsolePeer).toHaveBeenCalledWith({ hostname: "vnk-itd-sa03", profile: "client" }),
    );
  });

  it("dismisses a machine", async () => {
    renderPanel();
    await screen.findByText("vna-mgr-101");

    fireEvent.click(screen.getAllByRole("button", { name: /Скрыть/ })[1]);

    await waitFor(() => expect(api.dismissConsolePeer).toHaveBeenCalledWith("vna-mgr-101"));
  });

  it("renders nothing when every console machine is already listed", async () => {
    api.getUnlistedConsolePeers.mockResolvedValue(response({ data: [], count: 0 }));
    const { container } = renderPanel();

    await waitFor(() => expect(api.getUnlistedConsolePeers).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing while the console is unreachable (the page already warns about that)", async () => {
    api.getUnlistedConsolePeers.mockResolvedValue(response({ data: [], count: 0, console_reachable: false }));
    const { container } = renderPanel();

    await waitFor(() => expect(api.getUnlistedConsolePeers).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("never asks the server for a non-superuser", () => {
    const { container } = renderPanel(false);

    expect(api.getUnlistedConsolePeers).not.toHaveBeenCalled();
    expect(container).toBeEmptyDOMElement();
  });

  it("mentions console entries that have no hostname", async () => {
    api.getUnlistedConsolePeers.mockResolvedValue(response({ nameless_peers: 3 }));
    renderPanel();

    expect(await screen.findByText(/Ещё 3 записей в консоли без имени/)).toBeInTheDocument();
  });
});
