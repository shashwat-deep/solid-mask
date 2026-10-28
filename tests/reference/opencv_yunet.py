"""Reference boxes for tests/app/eval-page.spec.ts: OpenCV's own YuNet detector on the test photo.

    python -m pip install -r tests/reference/requirements.txt
    python tests/reference/opencv_yunet.py > tests/reference/opencv_yunet.txt

Needs app/models/face_detection_yunet_2023mar.onnx (`npm run fetch-model` in app/) and
tests/fixtures/data/glover.jpg (`npm run fixtures` in tests/). Runs cv2.FaceDetectorYN on the photo as the app
sees it: shrunk with INTER_AREA so the long side is 640 px, score threshold 0.05, NMS IoU 0.3, top_k 5000. Prints
every box in pixels of the full photo, highest score first. OpenCV gives the model the 480 x 640 image as it is,
while the app letterboxes it into 640 x 640; the two differ only in boxes at the right edge.
"""
from pathlib import Path
import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
MODEL = ROOT / 'app/models/face_detection_yunet_2023mar.onnx'
PHOTO = ROOT / 'tests/fixtures/data/glover.jpg'

image = cv2.imread(str(PHOTO), cv2.IMREAD_COLOR)  # BGR, as the model expects; the photo's EXIF orientation is 1
height, width = image.shape[:2]
scale = 640 / max(width, height)
size = (round(width * scale), round(height * scale))
detector = cv2.FaceDetectorYN.create(str(MODEL), '', size, 0.05, 0.3, 5000)
_, faces = detector.detect(cv2.resize(image, size, interpolation=cv2.INTER_AREA))

print(f'# OpenCV {cv2.__version__}, numpy {np.__version__}: {PHOTO.name} ({width} x {height}) shrunk to {size[0]} x {size[1]}')
print('# x y w h score, in pixels of the full photo, highest score first')
for face in sorted(faces if faces is not None else [], key=lambda f: -f[14]):
    x, y, w, h = (float(v) / scale for v in face[:4])
    print(f'{x:.3f} {y:.3f} {w:.3f} {h:.3f} {float(face[14]):.6f}')
