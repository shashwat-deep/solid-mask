// Decodes a saved copy and checks that the core of each face is the block colour.
import jpeg from 'jpeg-js';
import type { Face } from '../../fixtures/fetch.ts';
import { frameOf } from './jpeg.ts';

export type Rect = { x: number; y: number; w: number; h: number };
export type Rgb = { width: number; height: number; data: Uint8Array };

/** The block colour, #000000 (docs/contracts.md, section 2). */
export const BLOCK: readonly [number, number, number] = [0, 0, 0];
/** How far a decoded JPEG may differ from the block colour inside whole MCUs (docs/plan.md, privacy suite). */
export const JPEG_TOLERANCE = 2;

/** Decodes to 8-bit RGB with jpeg-js, a decoder independent of the browser that wrote the file. */
export function decodeRgb(bytes: Uint8Array): Rgb {
  const image = jpeg.decode(bytes, { useTArray: true, formatAsRGBA: false, maxMemoryUsageInMB: 1024 });
  return { width: image.width, height: image.height, data: image.data };
}

/**
 * The part of `rect` a decoder must reproduce exactly when all of `rect` is one colour: the whole
 * MCUs inside it, less 2 px at the edge, where decoders that smooth chroma across MCU boundaries
 * may blend in colour from outside.
 */
export function solidCore(rect: Rect, mcuWidth: number, mcuHeight: number): Rect {
  const x0 = Math.ceil(rect.x / mcuWidth) * mcuWidth + 2;
  const y0 = Math.ceil(rect.y / mcuHeight) * mcuHeight + 2;
  const x1 = Math.floor((rect.x + rect.w) / mcuWidth) * mcuWidth - 2;
  const y1 = Math.floor((rect.y + rect.h) / mcuHeight) * mcuHeight - 2;
  return { x: x0, y: y0, w: Math.max(0, x1 - x0), h: Math.max(0, y1 - y0) };
}

/** Counts the pixels in `rect` with any channel more than `tolerance` away from `colour`. */
export function countOff(image: Rgb, rect: Rect, colour: readonly number[], tolerance: number): { pixels: number; off: number; worst: number } {
  let off = 0;
  let worst = 0;
  for (let y = rect.y; y < rect.y + rect.h; y++) {
    for (let x = rect.x; x < rect.x + rect.w; x++) {
      const i = 3 * (y * image.width + x);
      const d = Math.max(
        Math.abs(image.data[i] - colour[0]),
        Math.abs(image.data[i + 1] - colour[1]),
        Math.abs(image.data[i + 2] - colour[2]),
      );
      if (d > tolerance) off++;
      if (d > worst) worst = d;
    }
  }
  return { pixels: rect.w * rect.h, off, worst };
}

/** One line per face whose core is not covered by the block colour; an empty list means every face is covered. */
export function facesCoveredProblems(bytes: Uint8Array, faces: Face[]): string[] {
  let frame;
  try {
    frame = frameOf(bytes);
  } catch (e) {
    return [`the saved copy is not a JPEG with one frame: ${(e as Error).message}`];
  }
  const image = decodeRgb(bytes);
  const problems: string[] = [];
  for (const face of faces) {
    const core = solidCore(face, frame.mcuWidth, frame.mcuHeight);
    if (core.w === 0 || core.h === 0) {
      problems.push(`face ${face.faceId}: its box holds no whole MCU, so it cannot be checked`);
      continue;
    }
    const { pixels, off, worst } = countOff(image, core, BLOCK, JPEG_TOLERANCE);
    if (off > 0) {
      problems.push(
        `face ${face.faceId}: ${off} of ${pixels} pixels in its box differ from the block colour by more than ` +
          `${JPEG_TOLERANCE} (largest difference ${worst})`,
      );
    }
  }
  return problems;
}
