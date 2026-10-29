// Face detection with ONNX Runtime Web, as docs/contracts.md (section 1) defines it.
import * as ort from 'onnxruntime-web/wasm';
import wasmUrl from 'onnxruntime-web/ort-wasm-simd-threaded.wasm?url';
import yunetUrl from '../../models/face_detection_yunet_2023mar.onnx?url';
import { YUNET } from './models.ts';
import { type Candidate, decodeOutputs, letterbox, nms, resizeArea, STRIDES, tileCandidates } from './yunet.ts';

export type Box = {
  x: number;     // left edge in pixels of the bitmap passed in (origin top-left, x to the right)
  y: number;     // top edge (y downwards)
  w: number;     // width in pixels
  h: number;     // height in pixels
  score: number; // detector confidence, 0 to 1
};

export type Tiling =
  | { kind: 'none' }                                      // long side resized to inputSize, one pass
  | { kind: 'tiles'; longSide: number; overlap: number }; // long side resized to longSide (never enlarged), cut into
                                                          // inputSize tiles overlapping by `overlap` (0 to 1), merged with NMS

export type DetectOptions = {
  model: 'yunet' | 'yolo5face';
  modelSource?: string | ArrayBuffer; // yunet: the bundled file by default; yolo5face: always a local file, never bundled
  inputSize: number;                  // 640 unless the protocol says otherwise
  tiling: Tiling;
  scoreThreshold: number;             // the app uses the value set by the evaluation; the eval runner uses 0.05
  nmsIoU: number;                     // fixed per model, recorded with every run
};

// ONNX Runtime loads its WebAssembly from this site, like every other file (CLAUDE.md, rule 2).
// One thread: more need cross-origin isolation, which GitHub Pages cannot give.
ort.env.wasm.wasmPaths = { wasm: wasmUrl };
ort.env.wasm.numThreads = 1;

// Non-maximum suppression runs on every box scoring at least this much, and the score threshold
// is applied after it, so filtering the eval runner's boxes (threshold 0.05) at a higher threshold
// gives exactly the boxes the app finds at that threshold (docs/contracts.md, section 1).
const NMS_FLOOR = 0.05;

const sessions = new Map<string | ArrayBuffer, Promise<ort.InferenceSession>>();
// The SHA-256 of each model as loaded, which every evaluation run records (docs/contracts.md, section 1).
const digests = new Map<string | ArrayBuffer, string>();

async function createSession(source: string | ArrayBuffer): Promise<ort.InferenceSession> {
  let model = source;
  if (typeof model === 'string') {
    const response = await fetch(model);
    if (!response.ok) throw new Error(`could not load ${model}: HTTP ${response.status}`);
    model = await response.arrayBuffer();
  }
  // crypto.subtle exists only in secure contexts (https, or localhost), so a dev server opened by its
  // network address on a phone skips it.
  if (globalThis.crypto?.subtle) {
    const digest = new Uint8Array(await crypto.subtle.digest('SHA-256', model));
    digests.set(source, Array.from(digest, (b) => b.toString(16).padStart(2, '0')).join(''));
  }
  const session = await ort.InferenceSession.create(new Uint8Array(model), { executionProviders: ['wasm'] });
  // One run on a blank input, so that nothing is left to load or compile when the first photo comes.
  const size = YUNET.inputSize;
  await session.run({ input: new ort.Tensor('float32', new Float32Array(3 * size * size), [1, 3, size, size]) });
  return session;
}

/**
 * Loads the detector and runs it once. The app calls this while the page loads, so that once it
 * says it is ready, nothing more is fetched (README, "It never uploads your photos").
 */
export function loadDetector(source: string | ArrayBuffer = yunetUrl): Promise<ort.InferenceSession> {
  let session = sessions.get(source);
  if (!session) {
    session = createSession(source);
    sessions.set(source, session);
    session.catch(() => sessions.delete(source));
  }
  return session;
}

/** The SHA-256 of the model loaded from source, once loadDetector() has read it. */
export function modelSha256(source: string | ArrayBuffer = yunetUrl): string | undefined {
  return digests.get(source);
}

/** The bitmap's RGBA pixels at full size. */
function readPixels(image: ImageBitmap): Uint8ClampedArray {
  // A canvas element, not OffscreenCanvas, which Safari lacks before 16.4.
  const canvas = document.createElement('canvas');
  canvas.width = image.width;
  canvas.height = image.height;
  const context = canvas.getContext('2d', { willReadFrequently: true });
  if (!context) throw new Error('no 2D canvas');
  context.drawImage(image, 0, 0);
  const pixels = context.getImageData(0, 0, image.width, image.height).data;
  // Free the canvas now, not at garbage collection: iOS Safari caps the memory all canvases may
  // hold together, and this one holds the uncovered photo.
  canvas.width = 0;
  canvas.height = 0;
  return pixels;
}

/** Runs the model on one input tensor: every candidate scoring at least minScore, in the tensor's pixels. */
async function detectTensor(session: ort.InferenceSession, tensor: Float32Array, size: number, minScore: number): Promise<Candidate[]> {
  const results = await session.run({ input: new ort.Tensor('float32', tensor, [1, 3, size, size]) });
  const outputs: Record<string, Float32Array> = {};
  for (const s of STRIDES) {
    for (const name of [`cls_${s}`, `obj_${s}`, `bbox_${s}`]) {
      const data = results[name]?.data;
      if (!(data instanceof Float32Array)) throw new Error(`the model gave no float32 output named ${name}`);
      outputs[name] = data;
    }
  }
  return decodeOutputs(outputs, size, minScore);
}

export async function detectFaces(image: ImageBitmap, options: DetectOptions): Promise<Box[]> {
  if (options.model !== 'yunet') throw new Error(`the ${options.model} model is not supported yet`);
  if (options.inputSize !== YUNET.inputSize) throw new Error(`${YUNET.file} takes ${YUNET.inputSize} px input only`);
  const { tiling } = options;
  if (tiling.kind === 'tiles') {
    if (!(Number.isInteger(tiling.longSide) && tiling.longSide > 0)) throw new Error(`longSide ${tiling.longSide} is not a whole number of pixels`);
    if (!(tiling.overlap >= 0 && tiling.overlap < 1)) throw new Error(`overlap ${tiling.overlap} is not from 0 to under 1`);
  }
  const session = await loadDetector(options.modelSource);

  const pixels = readPixels(image);
  const size = options.inputSize;
  const minScore = Math.min(NMS_FLOOR, options.scoreThreshold);
  let candidates: Candidate[];
  let scaleX: number;
  let scaleY: number;
  if (tiling.kind === 'none') {
    const boxed = letterbox(pixels, image.width, image.height, size);
    candidates = await detectTensor(session, boxed.tensor, size, minScore);
    ({ scaleX, scaleY } = boxed);
  } else {
    // The long side shrunk to longSide, never enlarged, then tiles of `size` that overlap by
    // `overlap` (docs/eval-protocol.md, part B, "tiled"). NMS runs once, over every tile's
    // candidates in the shrunk image's pixels, so a face that two tiles both find is kept once.
    const long = Math.max(image.width, image.height);
    const width = long > tiling.longSide ? Math.max(1, Math.round((image.width * tiling.longSide) / long)) : image.width;
    const height = long > tiling.longSide ? Math.max(1, Math.round((image.height * tiling.longSide) / long)) : image.height;
    const planes = resizeArea(pixels, image.width, image.height, width, height);
    const stride = Math.round(size * (1 - tiling.overlap));
    candidates = await tileCandidates(planes, width, height, size, stride, (tensor) => detectTensor(session, tensor, size, minScore));
    scaleX = width / image.width;
    scaleY = height / image.height;
  }

  return nms(candidates, options.nmsIoU)
    .filter((c) => c.score >= options.scoreThreshold)
    .map((c) => ({ x: c.x / scaleX, y: c.y / scaleY, w: c.w / scaleX, h: c.h / scaleY, score: c.score }));
}
