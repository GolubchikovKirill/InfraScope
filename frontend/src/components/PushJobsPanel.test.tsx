import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { vi } from "vitest";
import type { PushJob, PushJobsResponse } from "../client";

const api = vi.hoisted(() => ({ getPushJobs: vi.fn(), cancelPushJob: vi.fn() }));
vi.mock("../client", () => api);
const toast = vi.hoisted(() => vi.fn());
vi.mock("../lib/toastBus", () => ({ showToast: toast }));

import PushJobsPanel from "./PushJobsPanel";

const job = (hostname: string, over: Partial<PushJob> = {}): PushJob => ({
  id: `id-${hostname}`,
  device_id: null,
  hostname,
  profile: "client",
  dry_run: false,
  state: "queued",
  detail: null,
  requested_by: "admin@x",
  runner: null,
  created_at: new Date().toISOString(),
  started_at: null,
  finished_at: null,
  ...over,
});

const response = (data: PushJob[], runner: Partial<PushJobsResponse["runner"]> = {}): PushJobsResponse => ({
  data,
  count: data.length,
  runner: { name: null, seconds_ago: null, online: false, ...runner },
});

const renderPanel = () =>
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <PushJobsPanel />
    </QueryClientProvider>,
  );

beforeEach(() => {
  vi.clearAllMocks();
  api.cancelPushJob.mockResolvedValue({ message: "VNA-KKM-701: задание отменено" });
});

describe("PushJobsPanel", () => {
  it("says the runner is not connected when none has ever claimed, and tells how to start one", async () => {
    api.getPushJobs.mockResolvedValue(response([]));
    renderPanel();

    expect(await screen.findByText("раннер не подключён")).toBeInTheDocument();
    expect(screen.getByText(/Заданий пока нет/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Как подключить раннер" }));
    expect(screen.getByText(/Run-PushRunner\.ps1/)).toBeInTheDocument();
    expect(screen.getByText(/Сервер сам ничего не запускает на машинах/)).toBeInTheDocument();
  });

  it("shows a connected runner by name", async () => {
    api.getPushJobs.mockResolvedValue(response([job("VNA-KKM-701")], { name: "ADMIN-PC", seconds_ago: 5, online: true }));
    renderPanel();

    expect(await screen.findByText("раннер ADMIN-PC на связи")).toBeInTheDocument();
  });

  it("says a runner that stopped claiming is not answering", async () => {
    api.getPushJobs.mockResolvedValue(response([], { name: "ADMIN-PC", seconds_ago: 600, online: false }));
    renderPanel();

    expect(await screen.findByText(/раннер ADMIN-PC не отвечает/)).toBeInTheDocument();
  });

  it("lists each job with its state in words and the runner's detail", async () => {
    api.getPushJobs.mockResolvedValue(
      response([
        job("VNA-KKM-701", { state: "running" }),
        job("VNA-KKM-702", { state: "succeeded", detail: "RustDesk configured" }),
        job("VNA-KKM-703", { state: "failed", detail: "Access is denied" }),
        job("VNA-KKM-704", { state: "succeeded", dry_run: true, detail: "would push profile 'client'" }),
        job("VNA-KKM-705", { state: "skipped", detail: "Windows XP: RustDesk is not supported" }),
      ]),
    );
    renderPanel();

    expect(within(await screen.findByTestId("push-job-VNA-KKM-701")).getByText("выполняется")).toBeInTheDocument();
    expect(within(screen.getByTestId("push-job-VNA-KKM-702")).getByText("готово")).toBeInTheDocument();
    expect(within(screen.getByTestId("push-job-VNA-KKM-703")).getByText("Access is denied")).toBeInTheDocument();
    expect(within(screen.getByTestId("push-job-VNA-KKM-703")).getByText("ошибка")).toBeInTheDocument();
    expect(within(screen.getByTestId("push-job-VNA-KKM-704")).getByText("пробный прогон")).toBeInTheDocument();
    expect(within(screen.getByTestId("push-job-VNA-KKM-705")).getByText("пропущено")).toBeInTheDocument();
    expect(screen.getByText(/1 выполняется/)).toBeInTheDocument();
  });

  it("lets a waiting job be cancelled, but not one that is running", async () => {
    api.getPushJobs.mockResolvedValue(response([job("VNA-KKM-701"), job("VNA-KKM-702", { state: "running" })]));
    renderPanel();
    await screen.findByTestId("push-job-VNA-KKM-701");

    expect(screen.queryByRole("button", { name: "Отменить VNA-KKM-702" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Отменить VNA-KKM-701" }));

    await waitFor(() => expect(api.cancelPushJob).toHaveBeenCalledWith("id-VNA-KKM-701"));
    expect(toast).toHaveBeenCalledWith("VNA-KKM-701: задание отменено", "success");
  });

  it("says so when the queue cannot be read", async () => {
    api.getPushJobs.mockRejectedValue(new Error("boom"));
    renderPanel();

    expect(await screen.findByText("Не удалось получить очередь.")).toBeInTheDocument();
  });
});
