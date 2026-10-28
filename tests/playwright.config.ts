import { defineConfig, devices } from '@playwright/test';
import { APP_URL, EVAL_PAGE, EVAL_PORT, ORIGIN } from './env.ts';

export default defineConfig({
  // privacy/: the README's promises, on the production build. app/: the eval page, on the dev server.
  testDir: '.',
  testMatch: ['privacy/**/*.spec.ts', 'app/**/*.spec.ts'],
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
  webServer: [
    {
      command: 'node server.ts',
      url: `${ORIGIN}/__health`,
      reuseExistingServer: !process.env.CI,
    },
    {
      command: `npm --prefix ../app run dev -- --port ${EVAL_PORT} --strictPort --host 127.0.0.1`,
      url: EVAL_PAGE,
      reuseExistingServer: !process.env.CI,
    },
  ],
});
