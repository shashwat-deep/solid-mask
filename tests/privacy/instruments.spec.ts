// Checks of the checks. Each instrument the privacy tests rely on must catch the problem it looks
// for, or a passing privacy test would mean nothing. None of these need the app.
import { readFile } from 'node:fs/promises';
import { expect, test } from '@playwright/test';
import jpeg from 'jpeg-js';
import { ORIGIN } from '../env.ts';
import { hiddenDataProblems } from './helpers/jpeg.ts';
import { installProbe, probeLog, recordRequests } from './helpers/network.ts';
import { facesCoveredProblems } from './helpers/pixels.ts';
import { found, poisonedPhoto, samplesFound } from './helpers/poison.ts';
import { storageProblems } from './helpers/storage.ts';

test.describe('checks that run in Node', () => {
  // No browser is involved, so once is enough.
  test.skip(({ browserName }) => browserName !== 'chromium', 'runs once, in the chromium project');

  test('the hidden-data check finds everything planted in the poisoned photo', async () => {
    const photo = await poisonedPhoto();
    const bytes = new Uint8Array(await readFile(photo.path));
    const problems = hiddenDataProblems(bytes).join('\n');
    for (const planted of [
      'APP1 (Exif)',
      'APP1 (http://ns.adobe.com/xap/1.0/)',
      'APP11 (JP)',
      'APP13 (Photoshop 3.0)',
      'COM segment',
      'bytes after the end-of-image marker',
    ]) {
      expect(problems).toContain(planted);
    }
    // Kept from the source photo when it has them.
    if (photo.planted.includes('ICC_PROFILE')) expect(problems).toContain('APP2 (ICC_PROFILE)');
    if (photo.planted.includes('Adobe')) expect(problems).toContain('APP14 (Adobe)');
    expect(found(bytes, photo.planted)).toEqual(photo.planted);
    expect(photo.scanSamples.length).toBeGreaterThanOrEqual(32);
    expect(photo.previewSamples.length).toBeGreaterThanOrEqual(4);
    expect(samplesFound(bytes, photo.scanSamples)).toBe(photo.scanSamples.length);
    expect(samplesFound(bytes, photo.previewSamples)).toBe(photo.previewSamples.length);
  });

  test('the checks pass a plain, freshly encoded JPEG and fail an uncovered face', async () => {
    const photo = await poisonedPhoto();
    const source = jpeg.decode(await readFile(photo.sourcePath), { useTArray: true, formatAsRGBA: true, maxMemoryUsageInMB: 1024 });
    // A 1000 x 1000 crop around the first face keeps the encoding quick.
    const [face] = photo.faces;
    const crop = { x: face.x - 200, y: face.y - 200, w: 1000, h: 1000 };
    const shifted = photo.faces.map((f) => ({ ...f, x: f.x - crop.x, y: f.y - crop.y }));
    const pixels = new Uint8Array(4 * crop.w * crop.h);
    for (let y = 0; y < crop.h; y++) {
      const from = 4 * ((crop.y + y) * source.width + crop.x);
      pixels.set(source.data.subarray(from, from + 4 * crop.w), 4 * y * crop.w);
    }
    const encode = (): Uint8Array => new Uint8Array(jpeg.encode({ data: pixels, width: crop.w, height: crop.h }, 92).data);

    const uncovered = encode();
    expect(hiddenDataProblems(uncovered)).toEqual([]);
    expect(found(uncovered, photo.planted)).toEqual([]);
    expect(facesCoveredProblems(uncovered, shifted)).not.toEqual([]);

    // Paint each face box black (jpeg-js ignores the alpha channel).
    for (const f of shifted) {
      for (let y = f.y; y < f.y + f.h; y++) pixels.fill(0, 4 * (y * crop.w + f.x), 4 * (y * crop.w + f.x + f.w));
    }
    expect(facesCoveredProblems(encode(), shifted)).toEqual([]);
  });
});

test('the poisoned photo still opens in the browser', async ({ page }) => {
  const photo = await poisonedPhoto();
  const base64 = (await readFile(photo.path)).toString('base64');
  await page.goto(`${ORIGIN}/__health`);
  const size = await page.evaluate(async (data) => {
    const bitmap = await createImageBitmap(new Blob([Uint8Array.from(atob(data), (c) => c.charCodeAt(0))], { type: 'image/jpeg' }));
    return { width: bitmap.width, height: bitmap.height };
  }, base64);
  expect(size).toEqual({ width: photo.width, height: photo.height });
});

test('the storage check finds data planted in each kind of storage', async ({ context, page }) => {
  await page.goto(`${ORIGIN}/__health`);
  await page.evaluate(async () => {
    localStorage.setItem('photo', 'planted');
    sessionStorage.setItem('photo', 'planted');
    document.cookie = 'photo=planted';
    await new Promise((resolve, reject) => {
      const request = indexedDB.open('photos', 1);
      request.onupgradeneeded = () => request.result.createObjectStore('photos');
      request.onsuccess = () => resolve(request.result.close());
      request.onerror = () => reject(request.error);
    });
    await (await caches.open('photos')).put('/solid-mask/photo-1.jpg', new Response('planted'));
    try {
      await (await navigator.storage.getDirectory()).getFileHandle('photo.jpg', { create: true });
    } catch {
      // Not every engine offers the origin private file system to a test browser; the check reports that.
    }
  });

  const { problems, unavailable } = await storageProblems(page, context);
  const report = problems.join('\n');
  expect(report).toContain('localStorage key "photo"');
  expect(report).toContain('sessionStorage key "photo"');
  expect(report).toContain('IndexedDB database "photos"');
  expect(report).toContain('Cache API entry');
  expect(report).toContain('cookie "photo"');
  if (!unavailable.some((u) => u.startsWith('origin private file system'))) {
    expect(report).toContain('"photo.jpg" in the origin private file system');
  }
});

test('the network checks catch requests to other websites, sockets, and loads the policy blocked', async ({ context, page }) => {
  await installProbe(context);
  const requests = recordRequests(context);
  const elsewhere = 'http://localhost:4401';
  await page.route(`${ORIGIN}/__tracker`, (route) =>
    route.fulfill({
      contentType: 'text/html',
      body: `<!doctype html><img src="${elsewhere}/pixel.png"><script>new WebSocket("ws://localhost:4401/")</script>`,
    }),
  );
  await page.route(`${ORIGIN}/__blocked`, (route) =>
    route.fulfill({
      contentType: 'text/html',
      body: `<!doctype html><meta http-equiv="Content-Security-Policy" content="img-src 'none'"><img src="${elsewhere}/blocked.png">`,
    }),
  );

  await page.goto(`${ORIGIN}/__tracker`);
  await expect.poll(() => requests.all().map((r) => r.url)).toContain(`${elsewhere}/pixel.png`);
  await expect.poll(async () => (await probeLog(page)).map((e) => e.kind)).toContain('WebSocket');

  await page.goto(`${ORIGIN}/__blocked`);
  await expect.poll(async () => (await probeLog(page)).map((e) => e.kind)).toContain('blocked by the Content Security Policy');
});
