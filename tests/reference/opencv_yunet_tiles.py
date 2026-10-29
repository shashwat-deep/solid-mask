"""Reference boxes for the tiled setting: OpenCV's own YuNet detector, tile by tile, on the test photo.

    python -m pip install -r tests/reference/requirements.txt
    python tests/reference/opencv_yunet_tiles.py > tests/reference/opencv_yunet_tiles.txt

Needs app/models/face_detection_yunet_2023mar.onnx (`npm run fetch-model` in app/),
tests/fixtures/data/glover.jpg (`npm run fixtures` in tests/), and OpenCV and numpy as requirements.txt pins them.
Runs the tiled setting of docs/contracts.md (section 1) with longSide 1920, overlap 0.25 and input size 640, as in
docs/eval-protocol.md (part B): shrinks the photo with INTER_AREA so the long side is 1920 px (never enlarging it),
cuts it into 640 x 640 tiles 480 px apart, the last one at the image's edge, and runs cv2.FaceDetectorYN on each tile,
keeping every box that scores 0.05 or more, with no NMS inside a tile. Then it applies NMS once over the boxes of all
tiles, at IoU 0.3 in the shrunk image's pixels, and prints every box in pixels of the full photo, highest score first.
"""
from pathlib import Path
import math
import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
MODEL = ROOT / 'app/models/face_detection_yunet_2023mar.onnx'
PHOTO = ROOT / 'tests/fixtures/data/glover.jpg'

LONG_SIDE, OVERLAP = 1920, 0.25      # tiling: { kind: "tiles", longSide: 1920, overlap: 0.25 }
SIZE = 640                           # inputSize: every tile is SIZE x SIZE
FLOOR = 0.05                         # score floor inside each tile, and the score threshold after NMS
NMS_IOU = 0.3                        # nmsIoU for YuNet
CELLS = 80 * 80 + 40 * 40 + 20 * 20  # the model's grid at 640 x 640 (strides 8, 16, 32): the most boxes a tile gives


def round_half_up(v):
    """Nearest whole number, halves rounded up; Python's round() rounds halves to even."""
    whole = math.floor(v)
    return whole + 1 if v - whole >= 0.5 else whole


def tile_starts(n):
    """Tile starts along an axis of n pixels: 0, S, 2S, ... while start + SIZE < n, then n - SIZE."""
    if n <= SIZE:
        return [0]
    stride = round_half_up(SIZE * (1 - OVERLAP))
    starts = [0]
    while starts[-1] + stride + SIZE < n:
        starts.append(starts[-1] + stride)
    return starts + [n - SIZE]


def iou(a, b):
    """Intersection over union of two (x, y, w, h, ...) boxes; boxes that only touch give 0."""
    iw = min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])
    ih = min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1])
    if iw <= 0 or ih <= 0:
        return 0.0
    inter = iw * ih
    return inter / (a[2] * a[3] + b[2] * b[3] - inter)


image = cv2.imread(str(PHOTO), cv2.IMREAD_COLOR)  # BGR, as the model expects; the photo's EXIF orientation is 1
height, width = image.shape[:2]

# 1. Shrink so the long side is LONG_SIDE, by area averaging into 8-bit pixels; a smaller photo is used as it is.
if max(width, height) > LONG_SIDE:
    size = (round_half_up(width * LONG_SIDE / max(width, height)), round_half_up(height * LONG_SIDE / max(width, height)))
    shrunk = cv2.resize(image, size, interpolation=cv2.INTER_AREA)
else:
    shrunk = image
out_h, out_w = shrunk.shape[:2]

# 2. Tile starts along x and along y.
xs, ys = tile_starts(out_w), tile_starts(out_h)

# One detector for every tile. NMSBoxes, which FaceDetectorYN calls (OpenCV's modules/dnn/src/nms.inl.hpp), keeps a box
# whose overlap with a kept box is <= nms_threshold, so 1.0 suppresses nothing, and top_k CELLS drops nothing. It also
# keeps only scores strictly above the threshold, so the detector gets the float32 just below FLOOR and the floor
# itself is applied below.
detector = cv2.FaceDetectorYN.create(str(MODEL), '', (SIZE, SIZE), float(np.nextafter(np.float32(FLOOR), np.float32(0))),
                                     1.0, CELLS)

# 3. Tiles in row-major order, 0 where a tile extends past the shrunk image (only when that side is under SIZE).
# 4. Every box scoring FLOOR or more, with no NMS inside a tile. 5. Into the shrunk image's pixels.
candidates = []  # (x, y, w, h, score) in the shrunk image's pixels, tile by tile
for ty in ys:
    for tx in xs:
        tile = np.zeros((SIZE, SIZE, 3), np.uint8)
        part = shrunk[ty:ty + SIZE, tx:tx + SIZE]
        tile[:part.shape[0], :part.shape[1]] = part
        _, faces = detector.detect(tile)
        for face in faces if faces is not None else []:  # highest score first; equal scores in the model's grid order
            x, y, w, h, score = (float(v) for v in (*face[:4], face[14]))
            if score >= FLOOR:
                candidates.append((x + tx, y + ty, w, h, score))

# 6. NMS once over all tiles: highest score first, by a stable sort (equal scores keep tile order, then their order
# within the tile); a box is dropped when its IoU with a box already kept is greater than NMS_IOU.
kept = []
for box in sorted(candidates, key=lambda c: -c[4]):
    if all(iou(box, k) <= NMS_IOU for k in kept):
        kept.append(box)

# 7. Score filter after NMS.
kept = [box for box in kept if box[4] >= FLOOR]

print(f'# OpenCV {cv2.__version__}, numpy {np.__version__}: {PHOTO.name} ({width} x {height}) shrunk to {out_w} x {out_h}')
print(f'# tile starts: x {" ".join(map(str, xs))}, y {" ".join(map(str, ys))}')
print(f'# {len(xs) * len(ys)} tiles of {SIZE} x {SIZE}')
print(f'# {len(candidates)} candidates scoring {FLOOR} or more before NMS')
print('# x y w h score, in pixels of the full photo, highest score first')
for x, y, w, h, score in kept:  # 8. into the photo's pixels
    print(f'{x * width / out_w:.3f} {y * height / out_h:.3f} {w * width / out_w:.3f} {h * height / out_h:.3f} {score:.6f}')
