import { describe, expect, it } from 'vitest';
import {
  type Candidate,
  decodeOutputs,
  letterbox,
  nms,
  resizeArea,
  tile,
  tileCandidates,
  tiledSize,
  tileStarts,
} from '../../app/src/pipeline/yunet.ts';

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

  it('fills the height and leaves the columns right of the picture at zero when the photo is portrait', () => {
    const { tensor, scaleX, scaleY } = letterbox(image(2, 4, () => [200, 100, 50]), 2, 4, 8);
    const plane = 8 * 8;
    expect([scaleX, scaleY]).toEqual([2, 2]);
    expect([tensor[7 * 8 + 3], tensor[plane + 7 * 8 + 3], tensor[2 * plane + 7 * 8 + 3]]).toEqual([50, 100, 200]);
    for (let y = 0; y < 8; y++) expect([...tensor.subarray(y * 8 + 4, y * 8 + 8)]).toEqual([0, 0, 0, 0]);
  });
});

describe('resizeArea', () => {
  it('copies every pixel into B, G and R planes when the size does not change', () => {
    const planes = resizeArea(image(3, 2, (x, y) => [10 * x, 20 * y, 7]), 3, 2, 3, 2);
    expect([...planes]).toEqual([7, 7, 7, 7, 7, 7, 0, 0, 0, 20, 20, 20, 0, 10, 20, 0, 10, 20]);
  });

  it('rounds each average to the nearest whole value, halves up', () => {
    // Three pixels to two: (0 + 0.5 x 100) / 1.5 = 33.3 and (0.5 x 100 + 200) / 1.5 = 166.7.
    const thirds = resizeArea(image(3, 1, (x) => [[0, 100, 200][x], 0, 0]), 3, 1, 2, 1);
    expect([...thirds.subarray(4, 6)]).toEqual([33, 167]);
    // Two pixels to one: (0 + 1) / 2 = 0.5.
    expect(resizeArea(image(2, 1, (x) => [x, 0, 0]), 2, 1, 1, 1)[2]).toBe(1);
  });
});

describe('tiledSize', () => {
  it('shrinks the long side to longSide, portrait or landscape, and the other side in proportion', () => {
    expect(tiledSize(3000, 4000, 1920)).toEqual({ width: 1440, height: 1920 });
    expect(tiledSize(4000, 3000, 1920)).toEqual({ width: 1920, height: 1440 });
    // 1365 x 1920 / 2048 = 1279.7: the sides round separately, so their scales differ slightly.
    expect(tiledSize(2048, 1365, 1920)).toEqual({ width: 1920, height: 1280 });
    expect(tiledSize(20000, 5, 1920)).toEqual({ width: 1920, height: 1 });
  });

  it('never enlarges an image whose long side is longSide or less', () => {
    expect(tiledSize(768, 1024, 1920)).toEqual({ width: 768, height: 1024 });
    expect(tiledSize(1000, 500, 1920)).toEqual({ width: 1000, height: 500 });
    expect(tiledSize(1920, 1080, 1920)).toEqual({ width: 1920, height: 1080 });
  });
});

describe('tile', () => {
  // B, G and R planes of a 5 x 3 image whose values say where they are: 10 x row + column, plus
  // 100 in G and 200 in R.
  const planes = Uint8ClampedArray.from({ length: 45 }, (_, i) => 100 * Math.floor(i / 15) + 10 * Math.floor((i % 15) / 5) + (i % 5));

  it('holds the pixels from (left, top) at its top-left and zeros past the image', () => {
    const tensor = tile(planes, 5, 3, 2, 1, 4);
    const plane = (c: number) => [...tensor.subarray(16 * c, 16 * (c + 1))];
    expect(plane(0)).toEqual([12, 13, 14, 0, 22, 23, 24, 0, 0, 0, 0, 0, 0, 0, 0, 0]);
    expect(plane(2)).toEqual([212, 213, 214, 0, 222, 223, 224, 0, 0, 0, 0, 0, 0, 0, 0, 0]);
  });
});

describe('tileStarts', () => {
  it('starts a tile every stride and moves the last one back to end at the edge', () => {
    // 640 px tiles overlapping by 25%: the protocol's tiled setting.
    expect(tileStarts(1920, 640, 480)).toEqual([0, 480, 960, 1280]);
    expect(tileStarts(1440, 640, 480)).toEqual([0, 480, 800]);
    expect(tileStarts(1024, 640, 480)).toEqual([0, 384]);
    expect(tileStarts(1120, 640, 480)).toEqual([0, 480]);
    expect(tileStarts(641, 640, 480)).toEqual([0, 1]);
    expect(tileStarts(640, 640, 480)).toEqual([0]);
    expect(tileStarts(300, 640, 480)).toEqual([0]);
  });

  it('covers every pixel, stays inside the edge and keeps neighbours overlapping by at least size - stride', () => {
    for (const stride of [160, 320, 480, 640]) {
      for (let length = 1; length <= 2000; length++) {
        const starts = tileStarts(length, 640, stride);
        expect(starts[0]).toBe(0);
        expect(starts.at(-1)).toBe(Math.max(0, length - 640));
        for (let i = 1; i < starts.length; i++) {
          expect(starts[i] - starts[i - 1]).toBeGreaterThan(0);
          expect(starts[i] - starts[i - 1]).toBeLessThanOrEqual(stride);
        }
      }
    }
  });

  it('refuses a stride under one pixel, which would never reach the edge', () => {
    expect(() => tileStarts(1000, 640, 0)).toThrow();
    expect(() => tileStarts(1000, 640, Number.NaN)).toThrow();
  });
});

describe('tileCandidates', () => {
  /** A detector that finds the bounding box of the B values of 255, scoring the share of a 100 x 100 square it sees. */
  const findSquare = async (tensor: Float32Array): Promise<Candidate[]> => {
    let [x0, y0, x1, y1] = [Infinity, Infinity, -1, -1];
    for (let i = 0; i < 640 * 640; i++) {
      if (tensor[i] !== 255) continue;
      const [x, y] = [i % 640, Math.floor(i / 640)];
      [x0, y0, x1, y1] = [Math.min(x0, x), Math.min(y0, y), Math.max(x1, x), Math.max(y1, y)];
    }
    if (x1 < 0) return [];
    const [w, h] = [x1 - x0 + 1, y1 - y0 + 1];
    return [{ x: x0, y: y0, w, h, score: (w * h) / 10000 }];
  };

  /** The planes of a 1000 x 700 image, black but for a white 100 x 100 square with its top-left corner at (left, 300). */
  const squareAt = (left: number) =>
    resizeArea(image(1000, 700, (x, y) => (x >= left && x < left + 100 && y >= 300 && y < 400 ? [255, 255, 255] : [0, 0, 0])), 1000, 700, 1000, 700);

  it("gives each tile's candidates in the image's pixels, and one NMS merges the boxes tiles give for one face when they overlap by more than the limit", async () => {
    // Tiles start at x 0 and 360 and at y 0 and 60: the tiles at x 0 cut the square at x 640, the
    // tiles at x 360 hold all of it.
    const found = await tileCandidates(squareAt(600), 1000, 700, 640, 480, findSquare);
    const square = { x: 600, y: 300, w: 100, h: 100, score: 1 };
    const cut = { x: 600, y: 300, w: 40, h: 100, score: 0.4 };
    expect(found).toEqual([cut, square, cut, square]);
    expect(nms(found, 0.3)).toEqual([square]); // the cut boxes overlap the square by 0.4
  });

  it("keeps a tile's cut view of a face as a box of its own when it overlaps the whole face by the limit or less", async () => {
    // Moved to x 610, the square shows only 30 of its 100 columns in the tiles at x 0: IoU 0.3.
    const found = await tileCandidates(squareAt(610), 1000, 700, 640, 480, findSquare);
    expect(nms(found, 0.3)).toEqual([{ x: 610, y: 300, w: 100, h: 100, score: 1 }, { x: 610, y: 300, w: 30, h: 100, score: 0.3 }]);
  });

  it('runs one tile on an image no larger than a tile', async () => {
    const tensors: Float32Array[] = [];
    const planes = resizeArea(image(300, 200, () => [255, 255, 255]), 300, 200, 300, 200);
    const found = await tileCandidates(planes, 300, 200, 640, 480, async (tensor) => {
      tensors.push(tensor);
      return findSquare(tensor);
    });
    expect(tensors).toHaveLength(1);
    expect(found).toEqual([{ x: 0, y: 0, w: 300, h: 200, score: 6 }]);
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
