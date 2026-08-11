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
): Promise<string> {
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
  expect(code).toBeTruthy();
  return code || "";
}

test("UI pairing code connects, queues, revokes, and re-pairs", async ({
  extensionPage,
  context,
}) => {
  const options = await extensionPage("options");
  const code = await generatePairingCode(context.request);
  await options.locator("#serverUrl").fill(serverOrigin());
  await options.locator("#pairingCode").fill(code);
  await options.locator("#deviceName").fill("E2E browser");
  await options.locator("#pair").click();
  await expect(options.locator("#status")).toContainText(/Connected|Paired/i, {
    timeout: 30_000,
  });

  const stored = await storageSnapshot(options);
  expect(String(stored.apiToken || "")).toMatch(/^rdx_/);
  expect(JSON.stringify(stored)).not.toMatch(/RDK-[A-Z0-9]{4}-[A-Z0-9]{4}/);
  expect(stored.pairingCode).toBeUndefined();

  await queueViaWorker(options, SMOKE_OK);
  if (libraryDir()) {
    // Queue succeeded; device should appear in Settings.
  }

  const listed = await context.request.get(`${serverOrigin()}/settings`, {
    headers: { Authorization: basicAuthHeader() },
  });
  expect(await listed.text()).toContain("E2E browser");

  await options.locator("#disconnect").click();
  await expect(options.locator("#status")).toContainText(/Disconnected|revok/i, {
    timeout: 15_000,
  });

  const after = await storageSnapshot(options);
  expect(after.apiToken || "").toBe("");

  const again = await generatePairingCode(context.request);
  await options.locator("#pairingCode").fill(again);
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
  await options.close();
});
