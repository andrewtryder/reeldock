import {
  configureOptions,
  expect,
  extensionToken,
  notificationIds,
  popupQuery,
  serverOrigin,
  storageSnapshot,
  test,
} from "./fixtures";

test("options save, test connection, persist, and mask the token", async ({
  extensionPage,
  context,
}) => {
  const options = await extensionPage("options");
  const tokenInput = options.locator("#apiToken");
  await expect(tokenInput).toHaveAttribute("type", "password");

  await configureOptions(options);
  await expect(options.locator("#status")).toContainText(/Connected successfully/i, {
    timeout: 30_000,
  });

  await options.reload();
  await expect(options.locator("#serverUrl")).toHaveValue(serverOrigin());
  await expect(tokenInput).toHaveAttribute("type", "password");
  await expect(tokenInput).not.toHaveValue("");

  const stored = await storageSnapshot(options);
  expect(stored.apiToken).toBe(extensionToken());
  expect(stored.serverUrl).toBe(serverOrigin());
  expect(JSON.stringify(stored)).not.toMatch(/AUTH_USERNAME|AUTH_PASSWORD|admin:secret/);

  const root = await context.request.get(serverOrigin() + "/");
  expect(root.status()).toBe(401);
  await options.close();
});

test("queue Standard smoke video to Complete and notify once", async ({
  extensionPage,
  openSmokeTab,
}) => {
  await openSmokeTab("reeldockSmoke01");
  const options = await extensionPage("options");
  await configureOptions(options);
  await expect(options.locator("#status")).toContainText(/Connected successfully/i, {
    timeout: 30_000,
  });
  await options.close();

  const popup = await extensionPage("popup", popupQuery("reeldockSmoke01"));
  await expect(popup.locator("#video")).toContainText("ReelDock Release Smoke");
  await expect(popup.locator("#queue")).toBeEnabled();
  await popup.locator("#queue").click();
  await expect(popup.locator("#recent-list")).toContainText(/Complete/i, { timeout: 120_000 });

  await expect
    .poll(
      async () => {
        const notifications = await notificationIds(popup);
        return notifications.filter((id) => /^reeldock-(done|fail)-/.test(id));
      },
      { timeout: 15_000 },
    )
    .toEqual(expect.arrayContaining([expect.stringMatching(/^reeldock-done-/)]));
  const terminalIds = (await notificationIds(popup)).filter((id) =>
    /^reeldock-(done|fail)-/.test(id),
  );
  expect(terminalIds).toHaveLength(1);
  await popup.close();
});

async function ensureConnected(
  extensionPage: (
    name: "popup" | "options",
    query?: string,
  ) => Promise<import("@playwright/test").Page>,
) {
  const options = await extensionPage("options");
  await configureOptions(options);
  await expect(options.locator("#status")).toContainText(/Connected successfully/i, {
    timeout: 30_000,
  });
  await options.close();
}

test("close and reopen popup mid-job then reach Complete", async ({
  extensionPage,
  openSmokeTab,
}) => {
  await ensureConnected(extensionPage);
  await openSmokeTab("reeldockSmokeSlow01");
  const popup = await extensionPage("popup", popupQuery("reeldockSmokeSlow01"));
  await expect(popup.locator("#video")).toContainText("ReelDock Smoke Slow");
  await expect(popup.locator("#queue")).toBeEnabled();
  await popup.locator("#queue").click();
  await expect(popup.locator("#recent-list")).toContainText(/ReelDock Smoke Slow/);
  await popup.close();

  const again = await extensionPage("popup", popupQuery("reeldockSmokeSlow01"));
  await expect(again.locator("#recent-list")).toContainText("ReelDock Smoke Slow");
  await expect(again.locator("#recent-list")).toContainText(/Complete/i, { timeout: 120_000 });
  await again.close();
});

test("wrong token is actionable and recovering the token works", async ({ extensionPage }) => {
  const options = await extensionPage("options");
  await configureOptions(options, { token: "definitely-wrong-token" });
  await expect(options.locator("#status")).toContainText(/Invalid extension token/i, {
    timeout: 30_000,
  });

  const popup = await extensionPage("popup");
  await expect(popup.locator("#status")).toContainText(/Invalid extension token/i);

  await configureOptions(options);
  await expect(options.locator("#status")).toContainText(/Connected successfully/i, {
    timeout: 30_000,
  });
  await popup.reload();
  await expect(popup.locator("#status")).not.toContainText(/Invalid extension token/i);
  await options.close();
  await popup.close();
});

test("slow fixture can be cancelled", async ({ extensionPage, openSmokeTab }) => {
  await ensureConnected(extensionPage);
  await openSmokeTab("reeldockSmokeSlow01");
  const popup = await extensionPage("popup", popupQuery("reeldockSmokeSlow01"));
  await expect(popup.locator("#video")).toContainText("ReelDock Smoke Slow");
  await expect(popup.locator("#queue")).toBeEnabled();
  await popup.locator("#queue").click();
  await expect(popup.locator("#recent-list")).toContainText("ReelDock Smoke Slow");
  await popup.getByRole("button", { name: "Cancel" }).first().click();
  await expect(popup.locator("#recent-list")).toContainText(/Cancelled/i, { timeout: 30_000 });
  await popup.close();
});

test("fail fixture can be retried to Complete", async ({ extensionPage, openSmokeTab }) => {
  await ensureConnected(extensionPage);
  await openSmokeTab("reeldockSmokeFail01");
  const popup = await extensionPage("popup", popupQuery("reeldockSmokeFail01"));
  await expect(popup.locator("#video")).toContainText("ReelDock Smoke Fail");
  await expect(popup.locator("#queue")).toBeEnabled();
  await popup.locator("#queue").click();
  await expect(popup.locator("#recent-list")).toContainText(/Failed/i, { timeout: 120_000 });

  const before = await notificationIds(popup);
  const beforeDone = before.filter((id) => id.startsWith("reeldock-done-"));

  await popup.getByRole("button", { name: "Retry" }).first().click();
  await expect(popup.locator("#recent-list")).toContainText(/Complete/i, { timeout: 120_000 });

  await expect
    .poll(
      async () => {
        const after = await notificationIds(popup);
        return after.filter((id) => id.startsWith("reeldock-done-")).length;
      },
      { timeout: 15_000 },
    )
    .toBeGreaterThan(beforeDone.length);
  await popup.close();
});
