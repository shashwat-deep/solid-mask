// README, "What it never does with your photos":
//   It never uploads your photos. Once the page has loaded, it makes no network requests at all.
//   You can check this with airplane mode, as above.
import { expect, test } from '@playwright/test';
import { APP_URL } from '../env.ts';
import { maskAndSave, openApp } from './helpers/app.ts';
import { installProbe, onNetwork, probeLog, recordRequests } from './helpers/network.ts';
import { facesCoveredProblems } from './helpers/pixels.ts';
import { poisonedPhoto } from './helpers/poison.ts';

test('It never uploads your photos: no network request once the page has loaded, and it works offline', async ({ context, page }) => {
  const photo = await poisonedPhoto();
  await installProbe(context);
  const requests = recordRequests(context);

  await openApp(page);
  const loaded = requests.mark();
  const probedAtLoad = (await probeLog(page)).length;
  await context.setOffline(true); // airplane mode, as the README suggests

  const saved = await maskAndSave(page, photo.path);
  expect(facesCoveredProblems(saved.bytes, photo.faces), 'faces left uncovered in the copy saved offline').toEqual([]);

  expect(requests.since(loaded).filter(onNetwork), 'requests made after the page had loaded').toEqual([]);
  expect((await probeLog(page)).slice(probedAtLoad), 'sockets, WebRTC or WebTransport opened, or loads blocked, after the page had loaded').toEqual([]);
  // Playwright shows a service worker's requests in Chromium only, so these checks can't see them in
  // Firefox and WebKit. The app has no service worker; extend the checks before adding one.
  expect(await page.evaluate(async () => (await navigator.serviceWorker?.getRegistrations())?.length ?? 0), 'service workers').toBe(0);

  // The recorder was listening throughout: a request made now must show up in it.
  await context.setOffline(false);
  await page.evaluate((url) => fetch(url, { cache: 'no-store' }), APP_URL);
  expect(requests.since(loaded).map((r) => r.url), 'the recorder sees a request made after the test').toContain(APP_URL);
});
