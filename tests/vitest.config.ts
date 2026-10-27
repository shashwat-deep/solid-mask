import { defineConfig } from 'vitest/config';

// Unit tests of the app's pure functions, in Node. The privacy suite runs under Playwright.
export default defineConfig({
  test: {
    include: ['unit/**/*.test.ts'],
  },
});
