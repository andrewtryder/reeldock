import { expect, test } from "@playwright/test";

const SMOKE_URL = "https://www.youtube.com/watch?v=rdSmoke01001";

async function configureAbs(page: import("@playwright/test").Page) {
  await page.goto("/settings");
  await page.locator("#abs_base_url").fill("http://fake-abs:13378");
  await page.locator("#abs_api_token").fill("fake-abs-token");
  await page.locator("#abs-test-btn").click();
  await expect(page.locator("#abs-test-status")).toContainText(/Connected \(/, {
    timeout: 30_000,
  });
  const library = page.locator("#abs_library_id");
  await expect(library).toBeVisible();
  await library.selectOption({ label: "E2E Audiobooks (book)" });
  const scanToggle = page.locator('input[name="abs_scan_after_success"]');
  if (!(await scanToggle.isChecked())) {
    await scanToggle.check();
  }
  await page.locator('form.settings-form').getByRole("button", { name: /^Save$/i }).click();
  await expect(page.getByText("Settings saved successfully and reloaded.")).toBeVisible({
    timeout: 30_000,
  });
}

test("abs integration: configure → import → indexed", async ({ page }) => {
  await configureAbs(page);

  await page.goto("/");
  await page.locator('input[name="url"]').fill(SMOKE_URL);
  await page.locator("#preview-btn").click();
  await expect(page.locator("#import-form")).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText("ReelDock Release Smoke").first()).toBeVisible();

  const absScan = page.locator("#import_trigger_abs_scan");
  await expect(absScan).toBeVisible({ timeout: 15_000 });
  if (!(await absScan.isChecked())) {
    await absScan.check();
  }

  await page.locator("#create-btn").click();
  await expect(page).toHaveURL(/\/jobs\/[0-9a-f-]+/, { timeout: 30_000 });
  await expect(page.locator("#status-badge-container")).toContainText(/completed/i, {
    timeout: 120_000,
  });
  await expect(page.getByText("Added to Audiobookshelf")).toBeVisible({
    timeout: 120_000,
  });
  await expect(page.locator("#abs-open-link")).toBeVisible();
});
