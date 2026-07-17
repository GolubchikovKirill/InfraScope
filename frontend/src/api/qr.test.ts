import { describe, expect, it, vi } from "vitest";

import { normalizeDownloadError } from "./qr";

describe("QR download API", () => {
  it("extracts JSON details from blob error responses", async () => {
    const errorBlob = {
      text: vi.fn().mockResolvedValue(
        JSON.stringify({ detail: "Duty Free: не удалось подключиться к SQL" }),
      ),
    };
    const error = await normalizeDownloadError(
      {
        isAxiosError: true,
        message: "Request failed",
        response: {
          data: errorBlob,
        },
      },
      "Fallback error",
    );

    expect(error.message).toBe("Duty Free: не удалось подключиться к SQL");
  });
});
