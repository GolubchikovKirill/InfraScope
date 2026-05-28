import { expect, test } from "@playwright/test";

test("login page is reachable", async ({ page }) => {
  await page.goto("/login");
  await expect(page.getByText("Вход в систему")).toBeVisible();
  await expect(page.getByRole("button", { name: "Войти" })).toBeVisible();
});

