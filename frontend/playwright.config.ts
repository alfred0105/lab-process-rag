import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  reporter: 'list',
  timeout: 90_000,
  use: { ...devices['Desktop Chrome'], baseURL: 'http://127.0.0.1:5174', headless: true },
  webServer: {
    command: 'python3 e2e/run_environment.py',
    url: 'http://127.0.0.1:5174',
    cwd: process.cwd(),
    reuseExistingServer: false,
    timeout: 120_000,
  },
});
