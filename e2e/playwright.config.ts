import { defineConfig, devices } from "@playwright/test";

const baseURL = process.env.REELDOCK_BASE_URL || "http://127.0.0.1:18082";

export default defineConfig({
  testDir: "./tests",
  timeout: 180_000,
  expect: { timeout: 60_000 },
  fullyParallel: false,
  retries: 0,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL,
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
