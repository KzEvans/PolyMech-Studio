import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

// CSS preview only. Native WebView2 and system DPI acceptance is recorded separately.
for (const theme of ["light", "dark"] as const) {
  test(`Fluent CSS preview: ${theme}`, async ({ page, browserName }, testInfo) => {
    test.skip(browserName !== "chromium");
    await page.addInitScript(() => { window.__POLYMECH_PLATFORM__ = "windows"; });
    await page.request.put("http://127.0.0.1:8775/api/settings", { data: { theme } });
    await page.goto("/settings");
    await expect(page.getByText("本机 Origin", { exact: true }).first()).toBeVisible();
    await expect(page.locator("html")).toHaveAttribute("data-platform", "windows");
    await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
    await expect(page.getByRole("button", { name: "测试连接", exact: true })).toBeEnabled();
    await page.waitForTimeout(400); // let the enable/disable color transition settle
    const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
    expect(results.violations).toEqual([]);
    await page.screenshot({ path: testInfo.outputPath(`fluent-${theme}.png`), fullPage: true });
    await page.keyboard.press("Control+Alt+s");
    await expect(page.getByRole("complementary", { name: "主导航" })).not.toBeVisible();
    await page.keyboard.press("Control+Alt+s");
    await expect(page.getByRole("complementary", { name: "主导航" })).toBeVisible();
  });
}
