import { test, expect } from "@playwright/test";

/**
 * Records a marketing demo video. Run with:
 *   npx playwright test demo.spec.ts --project=chromium-record
 * The recording is saved as a webm to tests/e2e/test-results/<run>/video.webm,
 * then ffmpeg in `scripts/demo-build.sh` post-processes into MP4 + GIF.
 */
test.describe.configure({ mode: "serial", timeout: 240_000 });

test("ScopeGraph 50s product tour", async ({ page }) => {
  // 1. Login screen
  await page.goto("/login");
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(2000);

  // 2. Fill credentials slowly so it reads on video
  const userInput = page.getByPlaceholder(/请输入账号|账号|用户名|username/i).first();
  await userInput.click();
  await userInput.pressSequentially("chem_user_a", { delay: 80 });
  await page.waitForTimeout(400);

  const pwInput = page.getByPlaceholder(/请输入密码|密码|password/i).first();
  await pwInput.click();
  await pwInput.pressSequentially("chemA123", { delay: 80 });
  await page.waitForTimeout(800);

  // Click the Sign-in button — Element-Plus renders "登 录" (with hairspace)
  const signInBtn = page.locator("button.login-btn").first()
    .or(page.getByRole("button", { name: /登\s*录|sign\s*in/i }).first());
  await signInBtn.click();

  // 3. Wait for chat view
  await page.waitForURL(/.*\/(chat|app)\/?$/i, { timeout: 15_000 }).catch(() => {});
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(2_000);

  // 4. Type a question — composer is a textarea with the company-A placeholder
  const composer = page.locator(".chat-input textarea").first()
    .or(page.locator("textarea").last());
  await composer.click();
  await composer.pressSequentially("化工企业A 2024 年 Scope1 排放是多少", { delay: 55 });
  await page.waitForTimeout(800);

  // 5. Send via Enter (Element Plus textarea sends on Enter via @keyup.enter)
  await composer.press("Enter");

  // 6. Wait for streaming reply: a "123" token visible in any chat bubble
  await page
    .locator("text=/123/")
    .first()
    .waitFor({ state: "visible", timeout: 110_000 });
  // Let a few more tokens stream in for visual effect
  await page.waitForTimeout(8_000);

  // 7. Navigate to Dashboard via Element Plus menu — exact Chinese label
  await page.locator(".el-menu-item:has-text(\"数据看板\")").first().click();
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(6_000);

  // 8. Navigate to Data Console
  await page.locator(".el-menu-item:has-text(\"碳数据查询\")").first().click();
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(6_000);

  // 9. Back to Chat to close strong on the answer
  await page.locator(".el-menu-item:has-text(\"对话助手\")").first().click();
  await page.waitForTimeout(3_500);

  expect(page.url()).toBeTruthy();
});
