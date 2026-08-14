import { Buffer } from "node:buffer";

import {
  configureOptions,
  expect,
  libraryDir,
  queueViaWorker,
  serverOrigin,
  SMOKE_OK,
  storageSnapshot,
  test,
} from "./fixtures";

function basicAuthHeader(): string {
  const user = process.env.REELDOCK_AUTH_USERNAME || "admin";
  const pass = process.env.REELDOCK_AUTH_PASSWORD || "secret";
  return `Basic ${Buffer.from(`${user}:${pass}`).toString("base64")}`;
}

async function generatePairingCode(
  request: import("@playwright/test").APIRequestContext,
): Promise<{ code: string; pairingId: string; html: string }> {
  const origin = serverOrigin();
  const settings = await request.get(`${origin}/settings`, {
    headers: { Authorization: basicAuthHeader() },
  });
  expect(settings.ok()).toBeTruthy();
  const html = await settings.text();
  const csrf = html.match(/name="csrf_token" value="([^"]+)"/)?.[1];
  expect(csrf).toBeTruthy();
  const created = await request.post(`${origin}/settings/extension/pair-code`, {
    headers: { Authorization: basicAuthHeader() },
    form: { csrf_token: csrf || "" },
  });
  expect(created.ok()).toBeTruthy();
  const body = await created.text();
  const code = body.match(/RDK-[A-Z0-9]{4}-[A-Z0-9]{4}/)?.[0];
  const pairingId = body.match(/data-pairing-id="([^"]+)"/)?.[1];
  expect(code).toBeTruthy();
  expect(pairingId).toBeTruthy();
  expect(body).toContain("Waiting for browser");
  return { code: code || "", pairingId: pairingId || "", html: body };
}

test("fresh popup asks to connect and keeps Queue disabled", async ({
  extensionPage,
  openSmokeTab,
}) => {
  await openSmokeTab(SMOKE_OK);
  const popup = await extensionPage("popup");
  await expect(popup.locator("#setup-panel")).toBeVisible();
  await expect(popup.locator("#setup-copy")).toContainText(/Connect ReelDock/i);
  await expect(popup.locator("#queue")).toBeDisabled();
  await expect(popup.locator("#open-options")).toBeVisible();
  await popup.close();
});

test("UI pairing code connects, queues, revokes, and re-pairs", async ({
  extensionPage,
  context,
}) => {
  const options = await extensionPage("options");
  await expect(options.locator("#import-defaults-group")).toBeHidden();
  const { code, pairingId } = await generatePairingCode(context.request);

  const pending = await context.request.get(
    `${serverOrigin()}/api/settings/extension/pairing/${pairingId}/status`,
    { headers: { Authorization: basicAuthHeader() } },
  );
  expect(pending.ok()).toBeTruthy();
  expect(await pending.json()).toMatchObject({ status: "pending" });

  await options.locator("#serverUrl").fill(serverOrigin());
  await options.locator("#pairingCode").fill(code);
  await options.locator("#deviceName").fill("E2E browser");
  await options.locator("#pair").click();
  await expect(options.locator("#status")).toContainText(/Connected|Paired/i, {
    timeout: 30_000,
  });
  await expect(options.locator("#import-defaults-group")).toBeVisible();
  await expect(options.locator("#connection-summary")).toContainText(/Connected/i);

  const stored = await storageSnapshot(options);
  expect(String(stored.apiToken || "")).toMatch(/^rdx_/);
  expect(String(stored.pairedServerInstanceId || "")).toBeTruthy();
  expect(JSON.stringify(stored)).not.toMatch(/RDK-[A-Z0-9]{4}-[A-Z0-9]{4}/);
  expect(stored.pairingCode).toBeUndefined();
  const optionsHtml = await options.content();
  expect(optionsHtml).not.toContain(String(stored.apiToken));

  const paired = await context.request.get(
    `${serverOrigin()}/api/settings/extension/pairing/${pairingId}/status`,
    { headers: { Authorization: basicAuthHeader() } },
  );
  expect(await paired.json()).toMatchObject({
    status: "paired",
    device: { display_name: "E2E browser" },
  });

  await queueViaWorker(options, SMOKE_OK);
  if (libraryDir()) {
    // Queue succeeded; device should appear in Settings.
  }

  const listed = await context.request.get(`${serverOrigin()}/settings`, {
    headers: { Authorization: basicAuthHeader() },
  });
  expect(await listed.text()).toContain("E2E browser");

  // Reopen options: still connected, defaults visible.
  await options.reload();
  await expect(options.locator("#import-defaults-group")).toBeVisible({ timeout: 15_000 });
  await expect(options.locator("#connection-summary")).toContainText(/Connected/i);

  await options.locator("#disconnect").click();
  await expect(options.locator("#status")).toContainText(/Disconnected|revok/i, {
    timeout: 15_000,
  });
  await expect(options.locator("#import-defaults-group")).toBeHidden();

  const after = await storageSnapshot(options);
  expect(after.apiToken || "").toBe("");

  const again = await generatePairingCode(context.request);
  await options.locator("#pairingCode").fill(again.code);
  await options.locator("#pair").click();
  await expect(options.locator("#status")).toContainText(/Connected|Paired/i, {
    timeout: 30_000,
  });
  await options.close();
});

test("legacy token path still pairs via Advanced save", async ({ extensionPage }) => {
  const options = await extensionPage("options");
  await configureOptions(options);
  await expect(options.locator("#status")).toContainText(/Connected successfully/i, {
    timeout: 30_000,
  });
  await expect(options.locator("#import-defaults-group")).toBeVisible();
  await options.close();
});
