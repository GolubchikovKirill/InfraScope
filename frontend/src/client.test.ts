import axios from "axios";
import { vi } from "vitest";
import api from "./client";

describe("client interceptors", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
    Object.defineProperty(window, "location", {
      value: { href: "http://localhost/" },
      writable: true,
      configurable: true,
    });
  });

  it("adds bearer token to outgoing request headers", async () => {
    localStorage.setItem("access_token", "abc-token");
    const handlers = (api.interceptors.request as any).handlers;
    const fulfilled = handlers[0].fulfilled as (config: any) => any;
    const config = fulfilled({ headers: {} });
    expect(config.headers.Authorization).toBe("Bearer abc-token");
  });

  it("clears token when refresh fails after 401", async () => {
    localStorage.setItem("access_token", "abc-token");
    const handlers = (api.interceptors.response as any).handlers;
    const rejected = handlers[0].rejected as (error: any) => Promise<never>;

    // mock axios.post to simulate a failed /auth/refresh
    vi.spyOn(axios, "post").mockRejectedValue(new Error("Refresh failed"));

    await expect(rejected({ response: { status: 401 }, config: { url: "/test" } })).rejects.toBeTruthy();
    expect(localStorage.getItem("access_token")).toBeNull();
  });

  it("does not log out on 403 responses", async () => {
    localStorage.setItem("access_token", "abc-token");
    const handlers = (api.interceptors.response as any).handlers;
    const rejected = handlers[0].rejected as (error: any) => Promise<never>;

    await expect(rejected({ response: { status: 403 }, config: { url: "/admin" } })).rejects.toBeTruthy();
    expect(localStorage.getItem("access_token")).toBe("abc-token");
  });

  it("does not try refresh for auth endpoints", async () => {
    const handlers = (api.interceptors.response as any).handlers;
    const rejected = handlers[0].rejected as (error: any) => Promise<never>;
    const refreshSpy = vi.spyOn(axios, "post");

    await expect(rejected({ response: { status: 401 }, config: { url: "/auth/login" } })).rejects.toBeTruthy();
    await expect(rejected({ response: { status: 401 }, config: { url: "/auth/refresh" } })).rejects.toBeTruthy();
    expect(refreshSpy).not.toHaveBeenCalled();
  });

  it("refreshes token and retries original request", async () => {
    const handlers = (api.interceptors.response as any).handlers;
    const rejected = handlers[0].rejected as (error: any) => Promise<unknown>;

    vi.spyOn(axios, "post").mockResolvedValue({ data: { access_token: "new-token" } });
    const requestSpy = vi.spyOn(api, "request").mockResolvedValue({ data: { ok: true } } as any);

    const result = await rejected({
      response: { status: 401 },
      config: { url: "/printers", headers: {} },
    });

    expect(localStorage.getItem("access_token")).toBe("new-token");
    expect(requestSpy).toHaveBeenCalledTimes(1);
    const retriedConfig = requestSpy.mock.calls[0][0] as { headers?: Record<string, string> };
    expect(retriedConfig.headers?.Authorization).toBe("Bearer new-token");
    expect(result).toEqual({ data: { ok: true } });
  });

  it("queues parallel 401 requests while refresh is in progress", async () => {
    const handlers = (api.interceptors.response as any).handlers;
    const rejected = handlers[0].rejected as (error: any) => Promise<unknown>;

    let resolveRefresh: (value: { data: { access_token: string } }) => void = () => {};
    const refreshPromise = new Promise<{ data: { access_token: string } }>((resolve) => {
      resolveRefresh = resolve;
    });

    vi.spyOn(axios, "post").mockReturnValue(refreshPromise as any);
    const requestSpy = vi.spyOn(api, "request").mockResolvedValue({ data: { ok: true } } as any);

    const first = rejected({ response: { status: 401 }, config: { url: "/switches", headers: {} } });
    const second = rejected({ response: { status: 401 }, config: { url: "/computers", headers: {} } });
    resolveRefresh({ data: { access_token: "queued-token" } });

    await expect(first).resolves.toEqual({ data: { ok: true } });
    await expect(second).resolves.toEqual({ data: { ok: true } });
    expect(requestSpy).toHaveBeenCalledTimes(2);
    expect(localStorage.getItem("access_token")).toBe("queued-token");
  });
});
