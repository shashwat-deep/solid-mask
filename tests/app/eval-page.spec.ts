// The eval page (docs/contracts.md, section 3), used as eval/run_detect.py uses it: the image served on the
// page's own origin, the runner's detection options, and window.solidMask's four functions.
import { existsSync, readFileSync } from 'node:fs';
import { readdir, readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { expect, test, type Page } from '@playwright/test';
import jpeg from 'jpeg-js';
import { APP_DIST, EVAL_ORIGIN, EVAL_PAGE } from '../env.ts';
import { hiddenDataProblems } from '../privacy/helpers/jpeg.ts';
import { facesCoveredProblems } from '../privacy/helpers/pixels.ts';
import { poisonedPhoto } from '../privacy/helpers/poison.ts';

type Box = { x: number; y: number; w: number; h: number; score: number };
type SolidMask = {
  decode(url: string): Promise<ImageBitmap>;
  detectFaces(image: ImageBitmap, options: object): Promise<Box[]>;
  render(image: ImageBitmap, masks: Omit<Box, 'score'>[]): Promise<Blob>;
  info(): { ortVersion: string; backend: string; threads: number; modelSha256: string };
};

/** OpenCV's own YuNet boxes on the test photo, highest score first, as a script in tests/reference/ wrote them. */
function opencvBoxes(file: string): Box[] {
  return readFileSync(new URL(`../reference/${file}`, import.meta.url), 'utf8')
    .split('\n')
    .filter((line) => line.trim() && !line.startsWith('#'))
    .map((line) => {
      const [x, y, w, h, score] = line.trim().split(/\s+/).map(Number);
      return { x, y, w, h, score };
    });
}
// The single setting, from opencv_yunet.py, and the tiled one, from opencv_yunet_tiles.py.
const OPENCV = opencvBoxes('opencv_yunet.txt');
const OPENCV_TILES = opencvBoxes('opencv_yunet_tiles.txt');
// The boxes are compared down to 0.10: 7 in the single setting (the lowest scores 0.1037, the next 0.0827) and 16
// in the tiled one (0.1060, then 0.0939), so neither set is on a knife-edge. Below that, OpenCV's single-setting
// boxes differ from the app's at the right edge, where the app's 640 x 640 letterbox and OpenCV's 480 px wide input
// see different borders; the tiles are 640 x 640 in both.
const CLEAR_SCORE = 0.1;
// The runner uses Chromium (docs/contracts.md, section 3), and there the boxes must match to 0.5 px. Another
// engine may decode the JPEG a little differently (WebKit on macOS uses Apple's ImageIO), so it gets 2 px.
const tolerance = (browserName: string) => (browserName === 'chromium' ? { px: 0.5, score: 0.0005 } : { px: 2, score: 0.002 });

function expectNear(actual: Box, expected: Box, bound: { px: number; score: number }, what: string): void {
  for (const k of ['x', 'y', 'w', 'h'] as const) expect(Math.abs(actual[k] - expected[k]), `${what} ${k}`).toBeLessThanOrEqual(bound.px);
  expect(Math.abs(actual.score - expected.score), `${what} score`).toBeLessThanOrEqual(bound.score);
}

/** The boxes scoring CLEAR_SCORE or more match the expected ones in number, and each lies within the bound of one. */
function expectSameBoxes(found: Box[], expected: Box[], bound: { px: number; score: number }, what: string): void {
  const clear = (boxes: Box[]) => boxes.filter((b) => b.score >= CLEAR_SCORE);
  const unmatched = clear(found);
  expect(unmatched, `${what}: boxes scoring ${CLEAR_SCORE} or more`).toHaveLength(clear(expected).length);
  clear(expected).forEach((box, i) => {
    // Matched by position, not by rank: two scores 0.0005 apart may trade places in another engine.
    const distance = (b: Box) => Math.max(...(['x', 'y', 'w', 'h'] as const).map((k) => Math.abs(b[k] - box[k])));
    const nearest = unmatched.reduce((best, b) => (distance(b) < distance(best) ? b : best));
    unmatched.splice(unmatched.indexOf(nearest), 1);
    expectNear(nearest, box, bound, `${what} box ${i + 1}`);
  });
}
// The model's SHA-256 in the OpenCV Zoo, as fetch-model.ts checks it.
const MODEL_SHA256 = '8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4';
// The options eval/run_detect.py passes for YuNet in the single setting, and with --tiles 1920,0.25, the
// protocol's tiled setting (docs/eval-protocol.md, part B).
const RUNNER_OPTIONS = { model: 'yunet', inputSize: 640, tiling: { kind: 'none' }, scoreThreshold: 0.05, nmsIoU: 0.3 };
const TILED_OPTIONS = { ...RUNNER_OPTIONS, tiling: { kind: 'tiles', longSide: 1920, overlap: 0.25 } };
const ORT_VERSION: string = JSON.parse(
  readFileSync(new URL('../../app/node_modules/onnxruntime-web/package.json', import.meta.url), 'utf8'),
).version;

/** Serves bytes on the page's own origin, as the runner does, decodes and detects them, and renders the first box. */
async function runPage(page: Page, image: Uint8Array, options: object = RUNNER_OPTIONS) {
  const url = `${EVAL_ORIGIN}/__eval__/images/photo.jpg`;
  await page.route(url, (route) => route.fulfill({ body: Buffer.from(image), contentType: 'image/jpeg' }));
  await page.goto(EVAL_PAGE);
  await page.waitForFunction(() => (window as unknown as { solidMask?: unknown }).solidMask !== undefined);
  const result = await page.evaluate(
    async ({ url, options }) => {
      const api = (window as unknown as { solidMask: SolidMask }).solidMask;
      const bitmap = await api.decode(url);
      try {
        const boxes = await api.detectFaces(bitmap, options);
        const copy = new Uint8Array(await (await api.render(bitmap, boxes.slice(0, 1))).arrayBuffer());
        let binary = '';
        for (let i = 0; i < copy.length; i += 0x8000) binary += String.fromCharCode(...copy.subarray(i, i + 0x8000));
        return { info: api.info(), size: [bitmap.width, bitmap.height], boxes, copy: btoa(binary) };
      } finally {
        bitmap.close();
      }
    },
    { url, options },
  );
  return { ...result, copy: new Uint8Array(Buffer.from(result.copy, 'base64')) };
}

/**
 * The photo stored turned, as Open Images stores some photos: the pixels turned 90 degrees clockwise, with an
 * EXIF Orientation of 8 (turn 90 degrees counterclockwise to show), the tag eval/run_detect.py adds for Rotation 90.
 */
function storedTurned(source: Uint8Array): Uint8Array {
  const upright = jpeg.decode(source, { useTArray: true, formatAsRGBA: true, maxMemoryUsageInMB: 1024 });
  const { width, height } = upright;
  const turned = new Uint8Array(upright.data.length);
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      // Clockwise: upright (x, y) lands at (height - 1 - y, x) in an image height wide.
      turned.set(upright.data.subarray(4 * (y * width + x), 4 * (y * width + x) + 4), 4 * (x * height + (height - 1 - y)));
    }
  }
  // Quality 100 (all quantisation steps 1), so the copy's pixels stay within rounding of the photo's.
  const encoded = new Uint8Array(jpeg.encode({ data: turned, width: height, height: width }, 100).data);
  const tiff = [0x4d, 0x4d, 0, 0x2a, 0, 0, 0, 8, 0, 1, 0x01, 0x12, 0, 3, 0, 0, 0, 1, 0, 8, 0, 0, 0, 0, 0, 0];
  const payload = [...new TextEncoder().encode('Exif\0\0'), ...tiff];
  const app1 = [0xff, 0xe1, (payload.length + 2) >> 8, (payload.length + 2) & 0xff, ...payload];
  return Uint8Array.from([...encoded.subarray(0, 2), ...app1, ...encoded.subarray(2)]);
}

test('the eval page finds the boxes OpenCV finds, renders as the app saves, and reports its versions', async ({ page, browserName }) => {
  const photo = await poisonedPhoto();
  const result = await runPage(page, new Uint8Array(await readFile(photo.sourcePath)));

  expect(result.info, 'info()').toEqual({ ortVersion: ORT_VERSION, backend: 'wasm', threads: 1, modelSha256: MODEL_SHA256 });
  expect(result.size, 'decoded size').toEqual([photo.width, photo.height]);

  expectSameBoxes(result.boxes, OPENCV, tolerance(browserName), 'single');

  expect(facesCoveredProblems(result.copy, photo.faces), 'faces left uncovered by render()').toEqual([]);
  expect(hiddenDataProblems(result.copy), 'hidden data in the copy render() encodes').toEqual([]);
});

test('in the tiled setting, the eval page finds the boxes OpenCV finds tile by tile', async ({ page, browserName }) => {
  // OpenCV ran FaceDetectorYN on each of the 12 tiles of the photo shrunk to 1440 x 1920 and merged the boxes with
  // one NMS (tests/reference/opencv_yunet_tiles.py), so this checks the shrinking, the tile layout, the offsets
  // into the photo's pixels and the merge.
  const photo = await poisonedPhoto();
  const result = await runPage(page, new Uint8Array(await readFile(photo.sourcePath)), TILED_OPTIONS);
  expectSameBoxes(result.boxes, OPENCV_TILES, tolerance(browserName), 'tiled');
});

test('the eval page turns a photo stored turned upright by its EXIF orientation, as the runner relies on', async ({ page }) => {
  const photo = await poisonedPhoto();
  const result = await runPage(page, storedTurned(new Uint8Array(await readFile(photo.sourcePath))));

  expect(result.size, 'decoded size').toEqual([photo.width, photo.height]);
  // The turned copy was encoded again, nearly losslessly, which moves the face's box by under 1 px; allow 2. A
  // turn the wrong way, or none, would put the face hundreds of pixels away.
  expectNear(result.boxes[0], OPENCV[0], { px: 2, score: 0.002 }, 'face');
  expect(facesCoveredProblems(result.copy, photo.faces), 'faces left uncovered by render()').toEqual([]);
});

test('a reloaded eval page refuses to start, so a run cannot go on under changed code', async ({ page }) => {
  // Vite reloads the page when a source file changes; the runner must then fail, not go on.
  const ready = () => page.evaluate(() => (window as unknown as { solidMask?: unknown }).solidMask !== undefined);
  await page.goto(EVAL_PAGE);
  await expect.poll(ready, { message: 'the page is ready after opening it', timeout: 120_000 }).toBe(true);
  const refusal = page.waitForEvent('pageerror');
  await page.reload();
  expect((await refusal).message, 'the reloaded page says why it stopped').toContain('reloaded');
  expect(await ready(), 'window.solidMask after the reload').toBe(false);
});

test.describe('the deployed build', () => {
  test.skip(({ browserName }) => browserName !== 'chromium', 'no browser involved: runs once, in the chromium project');

  test('leaves the eval page out', async () => {
    expect(existsSync(join(APP_DIST, 'eval.html')), 'app/dist/eval.html').toBe(false);
    const scripts = (await readdir(join(APP_DIST, 'assets'))).filter((f) => f.endsWith('.js'));
    expect(scripts.length, 'the build has scripts').toBeGreaterThan(0);
    for (const script of scripts) {
      expect(await readFile(join(APP_DIST, 'assets', script), 'utf8'), `${script} holds no eval code`).not.toContain('solidMask');
    }
  });
});
