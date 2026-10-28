// The eval page (docs/contracts.md, section 3): the app's own decoding, detection, masking and encoding,
// for eval/run_detect.py to drive in headless Chromium. Development only: `npm run dev` serves
// app/eval.html, and the deployed build leaves it out.
import * as ort from 'onnxruntime-web/wasm';
import { decode } from './pipeline/decode.ts';
import { type Box, type DetectOptions, detectFaces, loadDetector } from './pipeline/detect.ts';
import { encodeJpeg } from './pipeline/encode.ts';
import { maskFor, paint } from './pipeline/mask.ts';
import { YUNET } from './pipeline/models.ts';

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

window.solidMask = {
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

  info() {
    return {
      ortVersion: ort.env.versions.web ?? ort.env.versions.common,
      backend: 'wasm',
      threads: ort.env.wasm.numThreads ?? 1,
      modelSha256: YUNET.sha256,
    };
  },
};

// Load and compile the model now, so the first image's time does not include it. A failure shows up
// on the first detectFaces() call.
loadDetector().catch(() => undefined);
