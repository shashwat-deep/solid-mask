// The eval page (docs/contracts.md, section 3): the app's own decoding, detection, masking and encoding,
// for eval/run_detect.py to drive in headless Chromium. Development only: `npm run dev` serves
// app/eval.html, and the deployed build leaves it out.
import * as ort from 'onnxruntime-web/wasm';
import { decode } from './pipeline/decode.ts';
import { type Box, type DetectOptions, detectFaces, loadDetector, modelSha256 } from './pipeline/detect.ts';
import { encodeJpeg } from './pipeline/encode.ts';
import { maskFor, paint } from './pipeline/mask.ts';

type SolidMask = {
  decode(url: string): Promise<ImageBitmap>;
  detectFaces(image: ImageBitmap, options: DetectOptions): Promise<Box[]>;
  render(image: ImageBitmap, masks: Pick<Box, 'x' | 'y' | 'w' | 'h'>[]): Promise<Blob>;
  info(): { ortVersion: string; backend: string; threads: number; modelSha256: string };
};

declare global {
  interface Window {
    solidMask: SolidMask;
  }
}

// Vite reloads the page when a source file changes. A run that went on after such a reload would mix two
// versions of the code under the one git commit the runner records, so a reloaded page refuses to start:
// the runner's next call then fails instead. Open the page again to use it.
const navigation = performance.getEntriesByType('navigation')[0] as PerformanceNavigationTiming | undefined;
if (navigation?.type === 'reload') {
  throw new Error('The eval page was reloaded, so its code may have changed during a run. Open it again.');
}

const solidMask: SolidMask = {
  /** Fetches the image, then decodes it upright, as the app decodes a chosen photo. */
  async decode(url) {
    const response = await fetch(url);
    if (!response.ok) throw new Error(`${url}: HTTP ${response.status}`);
    return decode(await response.blob());
  },

  detectFaces,

  /**
   * Draws the masks, already padded, and encodes exactly as the app saves. maskFor with no padding
   * rounds each mask outward to whole pixels and clips it, as the app does (docs/contracts.md, section 2).
   */
  async render(image, masks) {
    const canvas = document.createElement('canvas');
    paint(canvas, image, masks.map((m) => maskFor(m, 0, image.width, image.height)));
    return encodeJpeg(canvas);
  },

  /** Versions, and the SHA-256 of the model as loaded (empty if it did not load). */
  info() {
    return {
      ortVersion: ort.env.versions.web ?? ort.env.versions.common,
      backend: 'wasm',
      threads: ort.env.wasm.numThreads ?? 1,
      modelSha256: modelSha256() ?? '',
    };
  },
};

// window.solidMask appears once the model has loaded and compiled, so the runner's wait for it covers the
// loading and its first image is timed like the rest. If loading fails, the first detectFaces() call says why.
loadDetector()
  .catch(() => undefined)
  .then(() => {
    window.solidMask = solidMask;
  });
