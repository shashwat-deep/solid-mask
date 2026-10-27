import { defineConfig, devices } from '@playwright/test';
import { APP_URL, ORIGIN } from './env.ts';

export default defineConfig({
  testDir: './privacy',
  globalSetup: './global-setup.ts',
  // Each test decodes, masks and encodes a 12-megapixel photo, so it needs more than the default 30 s.
  timeout: 180_000,
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  // A privacy check that passes only on a retry has not passed.
  retries: 0,
  reporter: process.env.CI ? [['list'], ['github'], ['html', { open: 'never' }]] : [['list']],
  use: {
    baseURL: APP_URL,
    acceptDownloads: true,
    trace: 'retain-on-failure',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
    { name: 'firefox', use: { ...devices['Desktop Firefox'] } },
    { name: 'webkit', use: { ...devices['Desktop Safari'] } },
  ],
  webServer: {
    command: 'node server.ts',
    url: `${ORIGIN}/__health`,
    reuseExistingServer: !process.env.CI,
  },
});
