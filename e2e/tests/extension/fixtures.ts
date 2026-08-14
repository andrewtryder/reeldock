import { test as base, chromium, type BrowserContext, type Page } from "@playwright/test";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

export const SMOKE_OK = "rdSmoke01001";
export const SMOKE_FAIL = "rdSmokeFail1";
export const SMOKE_SLOW = "rdSmokeSlow1";

export const SMOKE_TITLES: Record<string, string> = {
  [SMOKE_OK]: "ReelDock Release Smoke",
  [SMOKE_FAIL]: "ReelDock Smoke Fail",
  [SMOKE_SLOW]: "ReelDock Smoke Slow",
};

export function smokeUrl(videoId: string): string {
  return `https://www.youtube.com/watch?v=${videoId}`;
}

export function extensionDist(): string {
  const candidates = [
    process.env.EXTENSION_DIST,
    path.resolve(process.cwd(), "../browser-extension/dist/chrome"),
    path.resolve(process.cwd(), "browser-extension/dist/chrome"),
  ].filter((value): value is string => Boolean(value));
  for (const candidate of candidates) {
    const dist = path.resolve(candidate);
    if (fs.existsSync(path.join(dist, "manifest.json"))) return dist;
  }
  throw new Error(
    `Unpacked Chrome extension not found. Run npm --prefix browser-extension run build:chrome`,
  );
}

export function serverOrigin(): string {
  return (process.env.REELDOCK_BASE_URL || "http://127.0.0.1:18083").replace(/\/$/, "");
}

export function extensionToken(): string {
  return process.env.REELDOCK_EXTENSION_TOKEN || "e2e-extension-token";
}

export function libraryDir(): string {
  return process.env.REELDOCK_LIBRARY_DIR || "";
}

async function installYouTubeMock(context: BrowserContext): Promise<void> {
  await context.route("https://www.youtube.com/watch?v=rdSmoke*", async (route) => {
    const url = new URL(route.request().url());
    const id = url.searchParams.get("v") || SMOKE_OK;
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
  context: async ({}, use) => {
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
  extensionId: async ({ context }, use) => {
    let [serviceWorker] = context.serviceWorkers();
    if (!serviceWorker) {
      serviceWorker = await context.waitForEvent("serviceworker");
    }
    const extensionId = new URL(serviceWorker.url()).host;
    await use(extensionId);
  },
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
  await page.locator("html[data-reeldock-ready='1']").waitFor({ timeout: 15_000 });
  await page.locator("#serverUrl").fill(options.serverUrl ?? serverOrigin());
  await page.locator("#legacy-token-wrap").evaluate((el) => {
    (el as HTMLDetailsElement).open = true;
  });
  await page.locator("#apiToken").fill(options.token ?? extensionToken());
  await page.locator("#save-legacy").click();
  await page.evaluate(async () => {
    const api = (globalThis as unknown as { chrome?: { storage: { local: { set: (v: object) => Promise<void> } } } }).chrome;
    if (api) await api.storage.local.set({ allowReimport: true });
  });
}

type QueueResult = {
  ok?: boolean;
  error?: string;
  job_id?: string;
  jobId?: string;
  title?: string;
};

export async function queueViaWorker(
  page: Page,
  videoId: string,
  extra: Record<string, unknown> = {},
): Promise<QueueResult> {
  const result = await page.evaluate(
    async ({ url, extra }) => {
      const api = (
        globalThis as unknown as {
          chrome?: {
            runtime: {
              sendMessage: (msg: Record<string, unknown>) => Promise<QueueResult>;
            };
          };
        }
      ).chrome;
      if (!api) return { ok: false, error: "chrome.runtime unavailable" };
      return api.runtime.sendMessage({
        action: "queue",
        source: "popup",
        url,
        allowReimport: true,
        ...extra,
      });
    },
    { url: smokeUrl(videoId), extra },
  );
  if (!result?.ok) {
    throw new Error(result?.error || "Queue via service worker failed");
  }
  return result;
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
  const fromApi = await page.evaluate(async () => {
    const api = (globalThis as unknown as { chrome?: ChromeNotifications }).chrome;
    if (!api?.notifications?.getAll) return [];
    return Object.keys(await api.notifications.getAll());
  });
  const fromWorker = await page.evaluate(async () => {
    const runtime = (
      globalThis as unknown as {
        chrome?: {
          runtime: {
            sendMessage: (msg: { action: string }) => Promise<{ ids?: string[] }>;
          };
        };
      }
    ).chrome;
    if (!runtime) return [];
    const res = await runtime.runtime.sendMessage({ action: "getNotificationIds" });
    return Array.isArray(res?.ids) ? res.ids : [];
  });
  return [...new Set([...fromApi, ...fromWorker])];
}
