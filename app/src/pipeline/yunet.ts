// The parts of YuNet face detection that need no ONNX Runtime: building the input tensor (one
// for the whole image, or one per tile), turning the outputs into boxes, and non-maximum
// suppression. Kept apart so they can be unit-tested in Node (tests/unit/).
//
// face_detection_yunet_2023mar.onnx takes "input", 1 x 3 x 640 x 640 float32 in BGR order with
// values 0 to 255 and no normalisation, the layout OpenCV's FaceDetectorYN gives it. For each
// stride s in 8, 16 and 32 it returns, per cell of a (640 / s) x (640 / s) grid in row-major order:
//   cls_s, obj_s  class and objectness scores; the face score is sqrt(cls * obj), each clamped to [0, 1]
//   bbox_s        dx, dy, log w, log h: the centre is (column + dx, row + dy) * s, the size exp(log w) * s
//   kps_s         five landmarks (not used here)

export type Candidate = { x: number; y: number; w: number; h: number; score: number };

export const STRIDES = [8, 16, 32] as const;

/**
 * For each output index along one axis, the first input index it covers and the weight of each
 * input index it covers: area averaging, the method of OpenCV's INTER_AREA when shrinking. The
 * results agree pixel for pixel except where an average falls exactly halfway between two whole
 * numbers: resizeArea rounds those up, while OpenCV's float32 sums can land on either side.
 */
function areaWeights(inSize: number, outSize: number): { first: Int32Array; weights: Float32Array[] } {
  const scale = inSize / outSize;
  const first = new Int32Array(outSize);
  const weights: Float32Array[] = [];
  for (let o = 0; o < outSize; o++) {
    const from = o * scale;
    const to = Math.min(inSize, (o + 1) * scale);
    const start = Math.floor(from);
    const end = Math.min(inSize, Math.ceil(to));
    const w = new Float32Array(end - start);
    for (let i = start; i < end; i++) w[i - start] = (Math.min(i + 1, to) - Math.max(i, from)) / (to - from);
    first[o] = start;
    weights.push(w);
  }
  return { first, weights };
}

/**
 * Resizes RGBA pixels to outW x outH by area averaging and rounds to whole values, halves up, as
 * an 8-bit image would. Returns the B, G and R planes, outW x outH each. The result does not
 * depend on the browser.
 */
export function resizeArea(rgba: Uint8ClampedArray, width: number, height: number, outW: number, outH: number): Uint8ClampedArray {
  const plane = outW * outH;
  const planes = new Uint8ClampedArray(3 * plane);
  if (outW === width && outH === height) {
    // Area averaging at the same size copies every pixel; this does the same, faster.
    for (let i = 0; i < plane; i++) {
      planes[i] = rgba[4 * i + 2];
      planes[plane + i] = rgba[4 * i + 1];
      planes[2 * plane + i] = rgba[4 * i];
    }
    return planes;
  }
  const cols = areaWeights(width, outW);
  const rows = areaWeights(height, outH);

  // Shrink every row to outW pixels.
  const narrow = new Float32Array(3 * outW * height);
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < outW; x++) {
      const w = cols.weights[x];
      let i = 4 * (y * width + cols.first[x]);
      let r = 0;
      let g = 0;
      let b = 0;
      for (let k = 0; k < w.length; k++, i += 4) {
        r += w[k] * rgba[i];
        g += w[k] * rgba[i + 1];
        b += w[k] * rgba[i + 2];
      }
      const n = 3 * (y * outW + x);
      narrow[n] = r;
      narrow[n + 1] = g;
      narrow[n + 2] = b;
    }
  }

  // Then every column to outH pixels, into the B, G and R planes.
  for (let y = 0; y < outH; y++) {
    const w = rows.weights[y];
    const top = rows.first[y];
    for (let x = 0; x < outW; x++) {
      let r = 0;
      let g = 0;
      let b = 0;
      for (let k = 0; k < w.length; k++) {
        const n = 3 * ((top + k) * outW + x);
        r += w[k] * narrow[n];
        g += w[k] * narrow[n + 1];
        b += w[k] * narrow[n + 2];
      }
      const o = y * outW + x;
      planes[o] = Math.round(b);
      planes[plane + o] = Math.round(g);
      planes[2 * plane + o] = Math.round(r);
    }
  }
  return planes;
}

/**
 * A `size` x `size` input tensor holding the pixels of B, G and R planes (width x height each)
 * from (left, top) at its top-left, and 0 wherever it reaches past them.
 */
export function tile(planes: Uint8ClampedArray, width: number, height: number, left: number, top: number, size: number): Float32Array {
  const tensor = new Float32Array(3 * size * size);
  const w = Math.min(size, width - left);
  const h = Math.min(size, height - top);
  for (let c = 0; c < 3; c++) {
    for (let y = 0; y < h; y++) {
      const from = c * width * height + (top + y) * width + left;
      tensor.set(planes.subarray(from, from + w), c * size * size + y * size);
    }
  }
  return tensor;
}

/**
 * Resizes RGBA pixels so the long side is `size`, by area averaging, rounds to whole values as an
 * 8-bit image would, and writes them as BGR planes into the top-left of a `size` x `size` tensor
 * whose other values are 0 (letterboxing). The result does not depend on the browser.
 */
export function letterbox(
  rgba: Uint8ClampedArray,
  width: number,
  height: number,
  size: number,
): { tensor: Float32Array; scaleX: number; scaleY: number } {
  const outW = Math.max(1, Math.round((width * size) / Math.max(width, height)));
  const outH = Math.max(1, Math.round((height * size) / Math.max(width, height)));
  const tensor = tile(resizeArea(rgba, width, height, outW, outH), outW, outH, 0, 0, size);
  return { tensor, scaleX: outW / width, scaleY: outH / height };
}

/**
 * The size the tiled setting shrinks an image to: its long side at most `longSide`, the other side
 * in proportion. An image already no longer keeps its size: the tiled setting never enlarges.
 */
export function tiledSize(width: number, height: number, longSide: number): { width: number; height: number } {
  const long = Math.max(width, height);
  if (long <= longSide) return { width, height };
  return {
    width: Math.max(1, Math.round((width * longSide) / long)),
    height: Math.max(1, Math.round((height * longSide) / long)),
  };
}

/**
 * Where the tiles start along a side of `length` pixels: every `stride` pixels while a tile still
 * ends before the edge, then once more so that the last tile ends exactly at the edge. No tile
 * reaches past the edge, and neighbours overlap by at least size - stride. A side no longer than
 * a tile gets one tile.
 */
export function tileStarts(length: number, size: number, stride: number): number[] {
  if (!(stride >= 1)) throw new Error(`a tile stride of ${stride} px would never reach the edge`);
  if (length <= size) return [0];
  const starts: number[] = [];
  for (let start = 0; start + size < length; start += stride) starts.push(start);
  starts.push(length - size);
  return starts;
}

/**
 * Cuts B, G and R planes (width x height each) into `size` x `size` tiles that start every
 * `stride` pixels (tileStarts), row by row, runs `detect` on each, and returns every tile's
 * candidates in the planes' pixels, ready for one NMS over all of them.
 */
export async function tileCandidates(
  planes: Uint8ClampedArray,
  width: number,
  height: number,
  size: number,
  stride: number,
  detect: (tensor: Float32Array) => Promise<Candidate[]>,
): Promise<Candidate[]> {
  const found: Candidate[] = [];
  for (const top of tileStarts(height, size, stride)) {
    for (const left of tileStarts(width, size, stride)) {
      for (const c of await detect(tile(planes, width, height, left, top, size))) {
        found.push({ ...c, x: c.x + left, y: c.y + top });
      }
    }
  }
  return found;
}

const clamp01 = (v: number): number => Math.min(1, Math.max(0, v));

/** Every grid cell scoring at least `minScore`, as a box in the pixels of the input tensor. */
export function decodeOutputs(outputs: Record<string, ArrayLike<number>>, size: number, minScore: number): Candidate[] {
  const found: Candidate[] = [];
  for (const s of STRIDES) {
    const cols = size / s;
    const cls = outputs[`cls_${s}`];
    const obj = outputs[`obj_${s}`];
    const bbox = outputs[`bbox_${s}`];
    for (let i = 0; i < cls.length; i++) {
      const score = Math.sqrt(clamp01(cls[i]) * clamp01(obj[i]));
      if (score < minScore) continue;
      const row = Math.floor(i / cols);
      const col = i % cols;
      const w = Math.exp(bbox[4 * i + 2]) * s;
      const h = Math.exp(bbox[4 * i + 3]) * s;
      found.push({ x: (col + bbox[4 * i]) * s - w / 2, y: (row + bbox[4 * i + 1]) * s - h / 2, w, h, score });
    }
  }
  return found;
}

export function iou(a: Candidate, b: Candidate): number {
  const w = Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x);
  const h = Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y);
  if (w <= 0 || h <= 0) return 0;
  const overlap = w * h;
  return overlap / (a.w * a.h + b.w * b.h - overlap);
}

/**
 * Greedy non-maximum suppression: highest score first, and a box is dropped when it overlaps a
 * kept box by more than `maxIoU`. Equal scores keep their input order.
 */
export function nms(candidates: Candidate[], maxIoU: number): Candidate[] {
  const kept: Candidate[] = [];
  for (const c of [...candidates].sort((a, b) => b.score - a.score)) {
    if (kept.every((k) => iou(k, c) <= maxIoU)) kept.push(c);
  }
  return kept;
}
