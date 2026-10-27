# Contracts

Version 0.2. The app and the evaluation both depend on what is written here. Change it only through a PR that both authors approve, and raise the version number.

Changes: 0.1 was the draft merged at M0. 0.2 rounds each mask outward to whole pixels (section 2).

## 1. Face detection

`app/src/pipeline/detect.ts` exports:

```ts
export type Box = {
  x: number;     // left edge in pixels of the bitmap passed in (origin top-left, x to the right)
  y: number;     // top edge (y downwards)
  w: number;     // width in pixels
  h: number;     // height in pixels
  score: number; // detector confidence, 0 to 1
};

export type Tiling =
  | { kind: "none" }                                      // long side resized to inputSize, one pass
  | { kind: "tiles"; longSide: number; overlap: number }; // long side resized to longSide (never enlarged), cut into
                                                          // inputSize tiles overlapping by `overlap` (0 to 1), merged with NMS

export type DetectOptions = {
  model: "yunet" | "yolo5face";
  modelSource?: string | ArrayBuffer; // yunet: the bundled file by default; yolo5face: always a local file, never bundled
  inputSize: number;                  // 640 unless the protocol says otherwise
  tiling: Tiling;
  scoreThreshold: number;             // the app uses the value set by the evaluation; the eval runner uses 0.05
  nmsIoU: number;                     // fixed per model, recorded with every run
};

export function detectFaces(image: ImageBitmap, options: DetectOptions): Promise<Box[]>;
```

- The app passes the upright bitmap from `createImageBitmap(file, { imageOrientation: "from-image" })`.
- The score filter runs after NMS. Filtering the runner's boxes at a higher threshold therefore gives the same boxes as running with that threshold, so the evaluation can sweep thresholds without rerunning detection.
- Every run records the ONNX Runtime Web version, the backend, the thread count and the model file's SHA-256.

## 2. Masks and the saved file

- A mask is a box grown by `pad × w` on the left and on the right and by `pad × h` at the top and at the bottom, then rounded outward to whole pixels (left and top edges down with `Math.floor`, right and bottom edges up with `Math.ceil`) and clipped to the image. The rounding means every pixel the mask touches is painted completely; a canvas fills a rectangle with fractional edges by blending the edge pixels with what lies under them. `eval/score.py` counts the same pixels. The evaluation sets `pad` (`docs/eval-protocol.md`, part B); the app keeps it in `app/src/config.ts`.
- A mask is a filled rectangle in `#000000` with alpha 1, drawn on the full-resolution canvas before encoding. Masks the user adds by hand follow the same rule, without padding.
- The saved file is a JPEG encoded from that canvas at quality 0.92 and named `masked-N.jpg`, where N counts from 1 within a session.

## 3. Eval page (app side, development only)

`app/eval.html` is a development entry point that is left out of the deployed build. It exposes:

```ts
window.solidMask = {
  decode(url: string): Promise<ImageBitmap>; // fetch, then createImageBitmap with imageOrientation "from-image"
  detectFaces(image: ImageBitmap, options: DetectOptions): Promise<Box[]>;
  render(image: ImageBitmap, masks: Box[]): Promise<Blob>; // draws the given masks (already padded) and encodes exactly as the app saves
  info(): { ortVersion: string; backend: string; threads: number; modelSha256: string };
};
```

The runner in `eval/` drives this page with Playwright in headless Chromium, so the evaluation runs the shipped decoding, preprocessing, inference and encoding.

## 4. Detections file (JSONL)

`results/detections/<run-id>.jsonl`. The first line describes the run; each later line holds one image under one transform and setting.

```json
{"run": "<run-id>", "model": "yunet", "modelSha256": "…", "ortVersion": "…", "backend": "wasm", "threads": 1, "nmsIoU": 0.3, "browser": "…", "manifestSha256": "…"}
{"imageId": "…", "transform": "none", "inputSize": 640, "tiling": {"kind": "none"}, "boxes": [[x, y, w, h, score]]}
```

`transform` is `none`, `rot<degrees>` (for example `rot45`) or `dark<EV>` (for example `dark2`). Boxes are raw: before padding, with every score at or above 0.05. The values shown are examples.

## 5. Bench result (JSON)

`results/bench/<device>-<browser>-<yyyy-mm-dd>-<n>.json`, one file per run on one device:

```json
{
  "device": "…", "os": "…", "browser": "…",
  "backend": "wasm", "threads": 1, "crossOriginIsolated": false,
  "model": "yunet", "modelBytes": 0, "modelSha256": "…",
  "inputSize": 640, "tiling": {"kind": "none"},
  "conditions": {"airplaneMode": true, "batteryPercent": 0, "charging": false, "batterySaver": false},
  "firstPhotoMs": 0,
  "photos": [{"id": "…", "width": 0, "height": 0, "decodeMs": 0, "detectMs": 0, "maskEncodeMs": 0, "totalMs": 0}]
}
```

`firstPhotoMs` covers the first photo of the run, including loading and compiling the model; `photos` holds the rest.

## 6. Manifests (CSV)

- `eval/manifest/images.csv`: `imageId, source, split, url, landingUrl, licence, author, authorUrl, title, sha256, width, height, rotation`. `split` is `tune` or `report` (`docs/eval-protocol.md`, part B).
- `eval/manifest/faces.csv`: `imageId, faceId, x, y, w, h, xMinNorm, xMaxNorm, yMinNorm, yMaxNorm, isOccluded, isTruncated, isDepiction, yaw`. `x, y, w, h` are pixels of the upright image after Open Images' rotation is applied; the `Norm` columns keep Open Images' original values. `yaw` stays empty until labelled.
- `app/bench/manifest.csv`: the bench photos, with the columns of `images.csv` except `split`.
