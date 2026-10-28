// The eval page (docs/contracts.md, section 3), used as eval/run_detect.py uses it: the image served on the
// page's own origin, the runner's detection options, and window.solidMask's four functions.
import { existsSync, readFileSync } from 'node:fs';
import { readdir, readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { expect, test } from '@playwright/test';
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

// OpenCV 4.13's FaceDetectorYN with face_detection_yunet_2023mar.onnx, on the test photo shrunk to 480 x 640
// with INTER_AREA: the face it finds, and how many boxes score 0.05 or more. The app must give the same.
const OPENCV_FACE = { x: 1164.3, y: 506.1, w: 744.1, h: 1062.1, score: 0.9436 };
const OPENCV_BOXES = 15;
// The model's SHA-256 in the OpenCV Zoo, as fetch-model.ts checks it.
const MODEL_SHA256 = '8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4';
// The options eval/run_detect.py passes for YuNet in the single setting.
const RUNNER_OPTIONS = { model: 'yunet', inputSize: 640, tiling: { kind: 'none' }, scoreThreshold: 0.05, nmsIoU: 0.3 };
const ORT_VERSION: string = JSON.parse(
  readFileSync(new URL('../../app/node_modules/onnxruntime-web/package.json', import.meta.url), 'utf8'),
).version;

test('the eval page finds the face OpenCV finds, renders as the app saves, and reports its versions', async ({ page }) => {
  const photo = await poisonedPhoto();
  const url = `${EVAL_ORIGIN}/__eval__/images/photo.jpg`;
  await page.route(url, (route) => route.fulfill({ path: photo.sourcePath, contentType: 'image/jpeg' }));
  await page.goto(EVAL_PAGE);
  await page.waitForFunction(() => (window as unknown as { solidMask?: unknown }).solidMask !== undefined);

  const result = await page.evaluate(
    async ({ url, options }) => {
      const api = (window as unknown as { solidMask: SolidMask }).solidMask;
      const image = await api.decode(url);
      try {
        const boxes = await api.detectFaces(image, options);
        const copy = new Uint8Array(await (await api.render(image, boxes.slice(0, 1))).arrayBuffer());
        let binary = '';
        for (let i = 0; i < copy.length; i += 0x8000) binary += String.fromCharCode(...copy.subarray(i, i + 0x8000));
        return { info: api.info(), size: [image.width, image.height], boxes, copy: btoa(binary) };
      } finally {
        image.close();
      }
    },
    { url, options: RUNNER_OPTIONS },
  );

  expect(result.info, 'info()').toEqual({ ortVersion: ORT_VERSION, backend: 'wasm', threads: 1, modelSha256: MODEL_SHA256 });
  expect(result.size, 'decoded size').toEqual([photo.width, photo.height]);

  expect(result.boxes, 'boxes scoring 0.05 or more').toHaveLength(OPENCV_BOXES);
  const [face] = result.boxes;
  for (const k of ['x', 'y', 'w', 'h'] as const) expect(Math.abs(face[k] - OPENCV_FACE[k]), `face ${k}`).toBeLessThanOrEqual(0.5);
  expect(Math.abs(face.score - OPENCV_FACE.score), 'face score').toBeLessThanOrEqual(0.0005);

  const copy = new Uint8Array(Buffer.from(result.copy, 'base64'));
  expect(facesCoveredProblems(copy, photo.faces), 'faces left uncovered by render()').toEqual([]);
  expect(hiddenDataProblems(copy), 'hidden data in the copy render() encodes').toEqual([]);
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
