import { expect, test } from "@playwright/test";

const SMOKE_URL = "https://www.youtube.com/watch?v=reeldockSmoke01";

test("golden path: home → preview → queue → Done", async ({ page }) => {
  await page.goto("/");

  await page.locator('input[name="url"]').fill(SMOKE_URL);
  await page.locator("#preview-btn").click();

  await expect(page.locator("#import-form")).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText("ReelDock Release Smoke").first()).toBeVisible();

  await page.locator("#create-btn").click();

  await expect(page).toHaveURL(/\/jobs\/[0-9a-f-]+/, { timeout: 30_000 });

  // Live polling + reload on terminal success; badge text becomes "completed".
  await expect(page.locator("#status-badge-container")).toContainText(/completed/i, {
    timeout: 120_000,
  });
  await expect(page.getByText("Done").first()).toBeVisible();
  await expect(page.locator("#processing-label")).toContainText(/COMPLETE/i);
});
