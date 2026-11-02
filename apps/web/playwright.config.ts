import { defineConfig, devices } from "@playwright/test";

// WebKit ≈ Safari / the macOS WebView Tauri would use; Chromium as second engine (SPEC §2.1).
// E2E runs on its own ports and a fresh data directory so it never touches real data.
const API_PORT = 8775;
const WEB_PORT = 5174;

export default defineConfig({
  testDir: "./e2e",
  timeout: 90_000,
  // Cold module loading and backend refreshes run under x64 emulation in the Windows VM.
  expect: { timeout: process.platform === "win32" ? 20_000 : 5_000 },
  workers: 1, // one shared backend database
  use: { baseURL: `http://127.0.0.1:${WEB_PORT}`, trace: "retain-on-failure", locale: "zh-CN" },
  projects: [
    { name: "webkit", use: { ...devices["Desktop Safari"], viewport: { width: 1440, height: 900 } } },
    { name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } },
  ],
  webServer: [
    {
      command: "node e2e/server.mjs api",
      url: `http://127.0.0.1:${API_PORT}/api/health`,
      reuseExistingServer: false,
    },
    {
      command: "node e2e/server.mjs web",
      url: `http://127.0.0.1:${WEB_PORT}`,
      reuseExistingServer: false,
    },
  ],
});
