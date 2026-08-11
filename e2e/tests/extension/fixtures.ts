import { test as base, chromium, type BrowserContext, type Page } from "@playwright/test";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));

export const SMOKE_TITLES: Record<string, string> = {
  reeldockSmoke01: "ReelDock Release Smoke",
  reeldockSmokeFail01: "ReelDock Smoke Fail",
  reeldockSmokeSlow01: "ReelDock Smoke Slow",
};

export function smokeUrl(videoId: string): string {
  return `https://www.youtube.com/watch?v=${videoId}`;
}

export function extensionDist(): string {
  const configured = process.env.EXTENSION_DIST;
  const dist = configured
    ? path.resolve(configured)
    : path.resolve(here, "../../../browser-extension/dist/chrome");
  if (!fs.existsSync(path.join(dist, "manifest.json"))) {
    throw new Error(
      `Unpacked Chrome extension not found at ${dist}. Run npm --prefix browser-extension run build:chrome`,
    );
  }
  return dist;
}

export function serverOrigin(): string {
  return (process.env.REELDOCK_BASE_URL || "http://127.0.0.1:18083").replace(/\/$/, "");
}

export function extensionToken(): string {
  return process.env.REELDOCK_EXTENSION_TOKEN || "e2e-extension-token";
}

async function installYouTubeMock(context: BrowserContext): Promise<void> {
  await context.route("https://www.youtube.com/watch?v=reeldockSmoke*", async (route) => {
    const url = new URL(route.request().url());
    const id = url.searchParams.get("v") || "reeldockSmoke01";
    const title = SMOKE_TITLES[id] || id;
    await route.fulfill({
      contentType: "text/html",
      body: `<!doctype html><html><head><title>${title}</title></head><body><h1>${title}</h1><p>${id}</p></body></html>`,
    });
  });
}

export const test = base.extend<{
  context: BrowserContext;
  extensionId: string;
  extensionPage: (name: "popup" | "options") => Promise<Page>;
  openSmokeTab: (videoId: string) => Promise<Page>;
}>({
  context: [
    // Shared profile so Options persist across the serial extension suite.
    async ({}, use) => {
      const userDataDir = fs.mkdtempSync(path.join(os.tmpdir(), "reeldock-ext-"));
      const headed = process.env.EXTENSION_E2E_HEADED === "1";
      const context = await chromium.launchPersistentContext(userDataDir, {
        channel: "chromium",
        headless: !headed,
        args: [
          `--disable-extensions-except=${extensionDist()}`,
          `--load-extension=${extensionDist()}`,
        ],
      });
      await installYouTubeMock(context);
      await use(context);
      await context.close();
    },
    { scope: "worker" },
  ],
  extensionId: [
    async ({ context }, use) => {
      let [serviceWorker] = context.serviceWorkers();
      if (!serviceWorker) {
        serviceWorker = await context.waitForEvent("serviceworker");
      }
      const extensionId = new URL(serviceWorker.url()).host;
      await use(extensionId);
    },
    { scope: "worker" },
  ],
  extensionPage: async ({ context, extensionId }, use) => {
    await use(async (name) => {
      const page = await context.newPage();
      await page.goto(`chrome-extension://${extensionId}/${name}.html`);
      return page;
    });
  },
  openSmokeTab: async ({ context }, use) => {
    await use(async (videoId) => {
      const page = await context.newPage();
      await page.goto(smokeUrl(videoId), { waitUntil: "domcontentloaded" });
      return page;
    });
  },
});

export const expect = test.expect;

export async function configureOptions(
  page: Page,
  options: { serverUrl?: string; token?: string } = {},
): Promise<void> {
  await page.locator("#serverUrl").fill(options.serverUrl ?? serverOrigin());
  await page.locator("#apiToken").fill(options.token ?? extensionToken());
  await page.locator("#save").click();
}

type ChromeStorage = {
  storage: { local: { get: (keys: null) => Promise<Record<string, unknown>> } };
};

export async function storageSnapshot(page: Page): Promise<Record<string, unknown>> {
  return page.evaluate(async () => {
    const api = (globalThis as unknown as { chrome?: ChromeStorage }).chrome;
    if (!api) return {};
    return api.storage.local.get(null);
  });
}

type ChromeNotifications = {
  notifications: { getAll: () => Promise<Record<string, unknown>> };
};

export async function notificationIds(page: Page): Promise<string[]> {
  return page.evaluate(async () => {
    const api = (globalThis as unknown as { chrome?: ChromeNotifications }).chrome;
    if (!api) return [];
    return Object.keys(await api.notifications.getAll());
  });
}
