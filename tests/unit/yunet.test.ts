import { describe, expect, it } from 'vitest';
import { type Candidate, decodeOutputs, letterbox, nms } from '../../app/src/pipeline/yunet.ts';

/** RGBA pixels from a function of position. */
function image(width: number, height: number, rgb: (x: number, y: number) => [number, number, number]): Uint8ClampedArray {
  const out = new Uint8ClampedArray(4 * width * height);
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) out.set([...rgb(x, y), 255], 4 * (y * width + x));
  return out;
}

describe('letterbox', () => {
  it('writes B, G and R planes scaled so the long side fills the input, and zeros elsewhere', () => {
    const { tensor, scaleX, scaleY } = letterbox(image(4, 2, () => [200, 100, 50]), 4, 2, 8);
    const plane = 8 * 8;
    expect([scaleX, scaleY]).toEqual([2, 2]);
    expect([tensor[0], tensor[plane], tensor[2 * plane]]).toEqual([50, 100, 200]);
    expect([tensor[3 * 8 + 7], tensor[plane + 3 * 8 + 7], tensor[2 * plane + 3 * 8 + 7]]).toEqual([50, 100, 200]);
    // Rows 4 to 7 lie below the picture.
    expect(tensor.subarray(4 * 8, plane).every((v) => v === 0)).toBe(true);
    expect(tensor.subarray(2 * plane + 4 * 8, 3 * plane).every((v) => v === 0)).toBe(true);
  });

  it('averages each block of pixels when shrinking', () => {
    const { tensor } = letterbox(image(4, 4, (x, y) => [x < 2 ? 0 : 100, y < 2 ? 0 : 200, 0]), 4, 4, 2);
    expect([...tensor.subarray(8, 12)]).toEqual([0, 100, 0, 100]); // R
    expect([...tensor.subarray(4, 8)]).toEqual([0, 0, 200, 200]); // G
  });

  it('weights pixels that fall partly in an output pixel by the share inside it', () => {
    // Three pixels to two: each output covers one and a half input pixels.
    const { tensor, scaleX } = letterbox(image(3, 1, (x) => [[0, 90, 180][x], 0, 0]), 3, 1, 2);
    expect(scaleX).toBeCloseTo(2 / 3);
    expect([tensor[8], tensor[9]]).toEqual([30, 150]); // (0 + 0.5 x 90) / 1.5 and (0.5 x 90 + 180) / 1.5
  });
});

describe('decodeOutputs', () => {
  const size = 64; // grids of 8 x 8, 4 x 4 and 2 x 2 cells

  /** Model outputs that are zero everywhere except the given cells. */
  function outputs(cells: { stride: 8 | 16 | 32; index: number; cls: number; obj: number; bbox: number[] }[]) {
    const out: Record<string, Float32Array> = {};
    for (const s of [8, 16, 32]) {
      const n = (size / s) ** 2;
      out[`cls_${s}`] = new Float32Array(n);
      out[`obj_${s}`] = new Float32Array(n);
      out[`bbox_${s}`] = new Float32Array(4 * n);
    }
    for (const c of cells) {
      out[`cls_${c.stride}`][c.index] = c.cls;
      out[`obj_${c.stride}`][c.index] = c.obj;
      out[`bbox_${c.stride}`].set(c.bbox, 4 * c.index);
    }
    return out;
  }

  it('places the box centre at (column + dx, row + dy) x stride, with size exp(log size) x stride', () => {
    // Stride 16: a 4 x 4 grid, so cell 6 is row 1, column 2.
    const [box] = decodeOutputs(outputs([{ stride: 16, index: 6, cls: 0.81, obj: 1, bbox: [0.5, 0.25, Math.log(2), Math.log(3)] }]), size, 0.5);
    expect(box.score).toBeCloseTo(0.9);
    expect(box.w).toBeCloseTo(32);
    expect(box.h).toBeCloseTo(48);
    expect(box.x).toBeCloseTo((2 + 0.5) * 16 - 16);
    expect(box.y).toBeCloseTo((1 + 0.25) * 16 - 24);
  });

  it('scores a cell sqrt(cls x obj), each clamped to [0, 1], and drops cells below the minimum', () => {
    const found = decodeOutputs(
      outputs([
        { stride: 8, index: 0, cls: 1.5, obj: 0.64, bbox: [0, 0, 0, 0] },
        { stride: 8, index: 1, cls: -0.2, obj: 1, bbox: [0, 0, 0, 0] },
        { stride: 32, index: 3, cls: 0.04, obj: 0.04, bbox: [0, 0, 0, 0] },
      ]),
      size,
      0.05,
    );
    expect(found.map((c) => c.score)).toEqual([expect.closeTo(0.8, 6)]);
  });
});

describe('nms', () => {
  const box = (x: number, y: number, w: number, h: number, score: number): Candidate => ({ x, y, w, h, score });

  it('keeps the higher-scoring of two boxes that overlap by more than the limit', () => {
    expect(nms([box(0, 0, 10, 10, 0.6), box(1, 1, 10, 10, 0.9)], 0.3)).toEqual([box(1, 1, 10, 10, 0.9)]);
  });

  it('keeps boxes that overlap by the limit or less', () => {
    // These overlap by 50 / 150 = 1/3.
    const kept = nms([box(0, 0, 10, 10, 0.9), box(5, 0, 10, 10, 0.8)], 1 / 3);
    expect(kept).toHaveLength(2);
  });

  it('finds the same boxes whether the score threshold is applied before or after it', () => {
    // docs/contracts.md, section 1: the eval runner keeps boxes down to 0.05 and filters later.
    // mulberry32: a seeded generator in exact 32-bit integer arithmetic.
    let seed = 1;
    const random = (): number => {
      seed = (seed + 0x6d2b79f5) | 0;
      let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 2 ** 32;
    };
    for (let trial = 0; trial < 200; trial++) {
      const candidates = Array.from({ length: 40 }, () =>
        box(random() * 100, random() * 100, 10 + random() * 30, 10 + random() * 30, 0.05 + 0.95 * random()),
      );
      for (const threshold of [0.05, 0.3, 0.5, 0.7, 0.9]) {
        const after = nms(candidates, 0.3).filter((c) => c.score >= threshold);
        const before = nms(candidates.filter((c) => c.score >= threshold), 0.3);
        expect(after).toEqual(before);
      }
    }
  });
});
