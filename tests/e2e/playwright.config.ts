import { defineConfig } from "@playwright/test";

/**
 * E2E test config.
 * Backend must be running on http://localhost:8002 with seeded users.
 * Frontend must be running on http://localhost:3000 (or whatever vite picks).
 *
 * Run before tests:
 *   cp ../../../AIconverstionSys/backend/.env ../../backend/.env
 *   sed -i '' 's/^PORT=8001$/PORT=8002/' ../../backend/.env
 *   PYTHONPATH=../../backend /Users/ant/anaconda3/envs/aics/bin/python3 ../../scripts/init_mysql.py
 *   PYTHONPATH=../../backend /Users/ant/anaconda3/envs/aics/bin/python3 -m uvicorn app.main:app --port 8002 &
 *   (cd ../../frontend && npm run dev &)
 */
export default defineConfig({
  testDir: ".",
  // Each chat call hits MiniMax 5+ times → easily 60-90s; give plenty of headroom.
  timeout: 240_000,
  expect: { timeout: 30_000 },
  workers: 1, // sequential — DB/Redis state is shared
  reporter: [["list"]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    actionTimeout: 30_000,
    navigationTimeout: 30_000,
  },
  projects: [
    { name: "chromium", use: { browserName: "chromium" } },
  ],
});
