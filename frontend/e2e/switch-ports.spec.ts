import { expect, test } from "@playwright/test";

test("switch ports modal supports safe write action", async ({ page }) => {
  await page.route("**/api/v1/users/me", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: "u1",
        email: "admin@example.com",
        full_name: "Admin",
        is_superuser: true,
      }),
    });
  });
  await page.route("**/api/v1/switches/?*", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        data: [
          {
            id: "sw1",
            name: "Main Switch",
            ip_address: "10.10.10.30",
            ssh_username: "admin",
            ssh_port: 22,
            ap_vlan: 20,
            vendor: "cisco",
            management_protocol: "snmp+ssh",
            snmp_version: "2c",
            snmp_community_ro: "public",
            snmp_community_rw: "private",
            model_info: "C2960",
            ios_version: "15.2(7)E",
            hostname: "SW-01",
            uptime: "2d",
            is_online: true,
            last_polled_at: null,
            created_at: new Date().toISOString(),
          },
        ],
        count: 1,
      }),
    });
  });
  await page.route("**/api/v1/switches/sw1/ports**", async (route) => {
    if (route.request().method() === "GET") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          data: [
            {
              port: "Gi0/1",
              if_index: 1,
              description: "AP uplink",
              admin_status: "up",
              oper_status: "up",
              speed_mbps: 1000,
              duplex: null,
              vlan: 20,
              poe_enabled: true,
              poe_power_w: 6.2,
              mac_count: null,
            },
          ],
          count: 1,
        }),
      });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ message: "ok" }),
    });
  });

  await page.addInitScript(() => {
    window.localStorage.setItem("access_token", "fake-token");
  });

  await page.goto("/switches");
  await expect(page.getByText("Сетевое оборудование")).toBeVisible();
  await page.getByRole("button", { name: "Порты свитча" }).click();
  await expect(page.getByText("Gi0/1")).toBeVisible();
  await page.getByRole("button", { name: "Down" }).click();
  await expect(page.getByText("Порты: Main Switch")).toBeVisible();
});
