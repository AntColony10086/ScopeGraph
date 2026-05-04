import { defineConfig } from "@playwright/test";

/** Recording-mode config: bigger viewport, video on, tracing off. */
export default defineConfig({
  testDir: ".",
  testMatch: /demo\.spec\.ts/,
  timeout: 240_000,
  expect: { timeout: 30_000 },
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    actionTimeout: 30_000,
    navigationTimeout: 30_000,
    viewport: { width: 1280, height: 720 },
    video: {
      mode: "on",
      size: { width: 1280, height: 720 },
    },
    headless: true,
  },
  projects: [{ name: "chromium-record", use: { browserName: "chromium" } }],
});
