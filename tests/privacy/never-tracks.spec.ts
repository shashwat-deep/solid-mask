// README, "What it never does with your photos":
//   It never tracks you. There are no accounts, ads, analytics, cookies or trackers, and nothing is
//   loaded from any other website, not even fonts.
import { expect, test, type Page } from '@playwright/test';
import { APP_URL, ORIGIN } from '../env.ts';
import { maskAndSave, openApp } from './helpers/app.ts';
import { installProbe, onNetwork, probeLog, recordRequests } from './helpers/network.ts';
import { facesCoveredProblems } from './helpers/pixels.ts';
import { poisonedPhoto } from './helpers/poison.ts';

// Sources a policy may name without letting the page load anything from another website.
const OWN_SOURCES = new Set(["'self'", "'none'", "'wasm-unsafe-eval'", 'blob:', 'data:']);

/** Problems with the page's Content Security Policy, the browser's own guard against other websites. */
async function policyProblems(page: Page): Promise<string[]> {
  const policies = await page.locator('meta[http-equiv="Content-Security-Policy" i]').evaluateAll((metas) =>
    metas.map((m) => m.getAttribute('content') ?? ''),
  );
  if (policies.length === 0) return ['no Content-Security-Policy meta tag'];
  const problems: string[] = [];
  for (const policy of policies) {
    const directives = policy
      .split(';')
      .map((d) => d.trim().split(/\s+/))
      .filter(([name]) => name);
    if (!directives.some(([name]) => name.toLowerCase() === 'default-src')) {
      problems.push(`"${policy}" has no default-src, so it allows anything it does not name`);
    }
    for (const [name, ...sources] of directives) {
      for (const source of sources) if (!OWN_SOURCES.has(source.toLowerCase())) problems.push(`${name} allows ${source}`);
    }
  }
  return problems;
}

test('It never tracks you: no cookies, and nothing loaded from any other website', async ({ context, page }) => {
  const photo = await poisonedPhoto();
  await installProbe(context);
  const requests = recordRequests(context);

  await openApp(page);
  const saved = await maskAndSave(page, photo.path);
  expect(facesCoveredProblems(saved.bytes, photo.faces), 'faces left uncovered in the saved copy').toEqual([]);

  const network = requests.all().filter(onNetwork);
  expect(network.map((r) => r.url), 'the recorder saw the page load').toContain(APP_URL);
  expect(network.filter((r) => new URL(r.url).origin !== ORIGIN), 'requests to other websites').toEqual([]);
  expect(await probeLog(page), 'sockets, WebRTC or WebTransport opened, or loads blocked').toEqual([]);
  expect(await context.cookies(), 'cookies').toEqual([]);
  expect(await page.evaluate(() => document.cookie), 'document.cookie').toBe('');
  expect(
    page.frames().map((f) => f.url()).filter((url) => url !== 'about:blank' && new URL(url).origin !== ORIGIN),
    'frames from other websites',
  ).toEqual([]);
  expect(await policyProblems(page), "the page's Content Security Policy").toEqual([]);
});
