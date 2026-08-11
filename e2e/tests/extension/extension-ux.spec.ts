import fs from "node:fs";
import path from "node:path";

import {
  configureOptions,
  expect,
  extensionToken,
  libraryDir,
  notificationIds,
  queueViaWorker,
  serverOrigin,
  SMOKE_FAIL,
  SMOKE_OK,
  SMOKE_SLOW,
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

async function ensureConnected(
  extensionPage: (name: "popup" | "options") => Promise<import("@playwright/test").Page>,
) {
  const options = await extensionPage("options");
  await configureOptions(options);
  await expect(options.locator("#status")).toContainText(/Connected successfully/i, {
    timeout: 30_000,
  });
  return options;
}

test("queue Standard smoke video to Complete and notify once", async ({
  extensionPage,
}) => {
  const options = await ensureConnected(extensionPage);
  await queueViaWorker(options, SMOKE_OK);
  await options.close();

  const popup = await extensionPage("popup");
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

test("close and reopen popup mid-job then reach Complete", async ({
  extensionPage,
}) => {
  const options = await ensureConnected(extensionPage);
  await queueViaWorker(options, SMOKE_SLOW);
  await options.close();

  const popup = await extensionPage("popup");
  await expect(popup.locator("#recent-list")).toContainText("ReelDock Smoke Slow");
  await popup.close();

  const again = await extensionPage("popup");
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

test("slow fixture can be cancelled", async ({ extensionPage }) => {
  const options = await ensureConnected(extensionPage);
  await queueViaWorker(options, SMOKE_SLOW);
  await options.close();

  const popup = await extensionPage("popup");
  await expect(popup.locator("#recent-list")).toContainText("ReelDock Smoke Slow");
  await popup.getByRole("button", { name: "Cancel" }).first().click();
  await expect(popup.locator("#recent-list")).toContainText(/Cancelled/i, { timeout: 30_000 });
  await popup.close();
});

test("fail fixture can be retried to Complete", async ({ extensionPage }) => {
  const options = await ensureConnected(extensionPage);
  await queueViaWorker(options, SMOKE_FAIL);
  await options.close();

  const popup = await extensionPage("popup");
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

test("Library root queues beside Theology instead of into it", async ({
  extensionPage,
  request,
}) => {
  const options = await ensureConnected(extensionPage);
  const dest = options.locator("#destinationSelect");
  await expect(dest).toBeVisible({ timeout: 15_000 });
  await dest.selectOption("__root__");
  await options.locator("#save").click();
  await expect(options.locator("#status")).toContainText(/Connected successfully/i, {
    timeout: 30_000,
  });

  const queued = await queueViaWorker(options, SMOKE_OK, {
    outputTitle: "Library Root Smoke",
  });
  const jobId = queued.job_id || queued.jobId;
  expect(jobId).toBeTruthy();

  const job = await request.get(`${serverOrigin()}/api/extension/jobs/${jobId}`, {
    headers: { Authorization: `Bearer ${extensionToken()}` },
  });
  expect(job.ok()).toBeTruthy();
  expect((await job.json()).destination_folder).toBe("");

  const popup = await extensionPage("popup");
  await expect(popup.locator("#recent-list")).toContainText(/Complete/i, { timeout: 120_000 });
  await popup.close();
  await options.close();

  const root = libraryDir();
  expect(root, "REELDOCK_LIBRARY_DIR must point at the Compose library bind").not.toBe("");
  const rootM4b = path.join(root, "Library Root Smoke.m4b");
  const theologyM4b = path.join(root, "Theology", "Library Root Smoke.m4b");
  await expect.poll(() => fs.existsSync(rootM4b), { timeout: 15_000 }).toBe(true);
  expect(fs.existsSync(theologyM4b)).toBe(false);
});
