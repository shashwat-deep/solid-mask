"""Measure how bright each face is: eval/manifest/luma.csv, for the measured-light breakdown of score.py.

    python eval/face_luma.py

docs/eval-protocol.md, part B, "Light, measured", compares the darkest tenth of faces with the rest. A face's
brightness is its mean luma: Y' = 0.299 R' + 0.587 G' + 0.114 B', the luma JPEG stores (BT.601 coefficients, on
0 to 255), of the image as Chromium decodes it (transforms.upright(): converted to sRGB by its ICC profile and
turned upright), averaged over the pixels whose centres lie inside the face's box. The script writes one row per
face of eval/manifest/faces.csv. Run it again whenever the manifest changes; a test checks that the two match.
"""
import argparse, math, sys
from pathlib import Path
import numpy as np
import build_manifest
import download
import transforms

ROOT = Path(__file__).resolve().parents[1]
BT601 = np.array([0.299, 0.587, 0.114])
LUMA_COLUMNS = ['imageId', 'faceId', 'meanLuma']


def inside(start, length):
    """The pixel indices whose centres lie in [start, start + length): index i has its centre at i + 0.5."""
    return range(math.ceil(start - 0.5), math.ceil(start + length - 0.5))


def mean_luma(luma, face):
    """Mean of the luma array (height x width) over the pixels whose centres lie inside the face's box."""
    x, y, w, h = (float(face[k]) for k in 'xywh')
    cols, rows = inside(x, w), inside(y, h)
    cols = range(max(cols.start, 0), min(cols.stop, luma.shape[1]))
    rows = range(max(rows.start, 0), min(rows.stop, luma.shape[0]))
    if not cols or not rows:
        raise ValueError(f'face {face["imageId"]} {face["faceId"]}: no pixel centre lies inside its box')
    return float(luma[rows.start:rows.stop, cols.start:cols.stop].mean())


def read_luma(path):
    """{(imageId, faceId): mean luma} from luma.csv."""
    return {(r['imageId'], r['faceId']): float(r['meanLuma']) for r in build_manifest.read_csv(path)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--manifest', type=Path, default=ROOT / 'eval/manifest')
    ap.add_argument('--images', type=Path, default=ROOT / 'data/openimages/images')
    args = ap.parse_args(argv)

    images = {r['imageId']: r for r in build_manifest.read_csv(args.manifest / 'images.csv')}
    faces = build_manifest.read_csv(args.manifest / 'faces.csv')
    by_image = {}
    for face in faces:
        by_image.setdefault(face['imageId'], []).append(face)
    values = {}
    for i, image_faces in by_image.items():
        row = images[i]
        upright = transforms.upright(download.image_path(args.images, i, row['url']), int(row['rotation']))
        luma = np.asarray(upright, dtype=np.float64) @ BT601
        if luma.shape != (int(row['height']), int(row['width'])):
            sys.exit(f'{i}: the upright image is {luma.shape[1]} x {luma.shape[0]}, the manifest says '
                     f'{row["width"]} x {row["height"]}')
        for face in image_faces:
            values[(i, face['faceId'])] = mean_luma(luma, face)
    build_manifest.write_csv(args.manifest / 'luma.csv', LUMA_COLUMNS, [
        {'imageId': f['imageId'], 'faceId': f['faceId'], 'meanLuma': f'{values[(f["imageId"], f["faceId"])]:.2f}'}
        for f in faces])
    print(f'mean luma of {len(faces)} faces in {len(by_image)} images: {args.manifest / "luma.csv"}')


if __name__ == '__main__':
    main()
