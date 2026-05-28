import { describe, expect, it, vi, beforeEach } from "vitest";

const mocks = vi.hoisted(() => ({
  getMock: vi.fn(),
  postMock: vi.fn(),
}));

vi.mock("./http", () => ({
  default: {
    get: mocks.getMock,
    post: mocks.postMock,
  },
}));

import { getMe } from "./auth";

describe("auth api", () => {
  beforeEach(() => {
    mocks.getMock.mockReset();
    mocks.postMock.mockReset();
  });

  it("uses /auth/me endpoint when available", async () => {
    mocks.getMock.mockResolvedValueOnce({
      data: { id: "u1", email: "admin@infrascope.dev", full_name: "Admin", is_superuser: true },
    });

    const user = await getMe();

    expect(mocks.getMock).toHaveBeenCalledWith("/auth/me");
    expect(mocks.postMock).not.toHaveBeenCalled();
    expect(user.email).toBe("admin@infrascope.dev");
  });

  it("falls back to /auth/test-token on 404", async () => {
    mocks.getMock.mockRejectedValueOnce({
      isAxiosError: true,
      response: { status: 404 },
    });
    mocks.postMock.mockResolvedValueOnce({
      data: { id: "u2", email: "ops@infrascope.dev", full_name: null, is_superuser: false },
    });

    const user = await getMe();

    expect(mocks.postMock).toHaveBeenCalledWith("/auth/test-token");
    expect(user.email).toBe("ops@infrascope.dev");
  });
});
