import { test, expect } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SHOTS_DIR = path.resolve(__dirname, "..", "..", "assets", "screenshots");

/**
 * Captures three product screenshots of the live UI:
 *   01-login.png      — login screen at rest
 *   02-chat.png       — chat with a completed Scope-1 query reply
 *   03-dashboard.png  — dashboard with KPI cards + charts
 *
 * Output: 1440 × 900 PNG, suitable for the README "Screenshots" section.
 */
test.describe.configure({ timeout: 240_000 });

test("capture three UI screenshots", async ({ browser }) => {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();

  // 1. Login at rest — wait for hero/card animations to settle
  await page.goto("/login");
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(1500);
  await page.screenshot({ path: path.join(SHOTS_DIR, "01-login.png"), fullPage: false });

  // 2. Login → Chat → ask question → wait for streamed reply → screenshot
  await page.getByPlaceholder(/请输入账号|账号|用户名/).first().fill("chem_user_a");
  await page.getByPlaceholder(/请输入密码|密码/).first().fill("chemA123");
  await page.locator("button.login-btn").first().click();

  await page.waitForURL(/.*\/(chat|app).*/, { timeout: 20_000 }).catch(() => {});
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(2_000);

  const composer = page.locator(".chat-input textarea").first();
  await composer.fill("化工企业A 2024 年 Scope1 排放是多少");
  await page.waitForTimeout(400);
  await composer.press("Enter");

  // Wait for the assistant reply to stream a "123" token in
  try {
    await page.locator("text=/123/").first().waitFor({ state: "visible", timeout: 180_000 });
    await page.waitForTimeout(8_000);
  } catch {
    // If LLM is slow, fall back to whatever is on screen at this moment
    await page.waitForTimeout(2_000);
  }
  await page.screenshot({ path: path.join(SHOTS_DIR, "02-chat.png"), fullPage: false });

  // 3. Dashboard
  await page.locator(".el-menu-item:has-text(\"数据看板\")").first().click();
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(4_000);
  await page.screenshot({ path: path.join(SHOTS_DIR, "03-dashboard.png"), fullPage: false });

  await ctx.close();
  expect(true).toBe(true);
});
