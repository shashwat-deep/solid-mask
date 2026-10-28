"""Score face detections against the manifest: missed faces, fully covered faces, detection recall, false masks.

    python eval/score.py results/detections/<run-id>.jsonl --pad 0.10 --threshold 0.50 [--split report]
    python eval/score.py results/detections/<run-id>.jsonl --operating-point

Implements docs/eval-protocol.md, part B, "Definitions" and "Operating point", for a detections file in the format
of docs/contracts.md, section 4, and the manifest in eval/manifest/. Padding and the score threshold are applied
here, so trying other values needs no new detection run.

A mask is every box with a score at or above the threshold, grown by pad × w on the left and right and pad × h at
the top and bottom, rounded outward to whole pixels and clipped to the image (docs/contracts.md, section 2): the
pixels the app paints. For each annotated face:
- coverage: the share of the face's box that the masks cover, computed exactly from those pixels; under a rotation
  (transform rot<degrees>) the box is the rotated quadrilateral (eval/transforms.py);
- protected: coverage of at least 90%; missed: not protected; complete: coverage of 100%;
- found: matched by a box before padding at IoU 0.5 or more, boxes taken in order of score and each box matching
  at most one face, the face it overlaps most (the usual detection recall).
A mask is false when its IoU with every annotated face, depictions included, is below 0.1.

The miss rate, the share covered completely and the recall count the faces that are not depictions; depictions
are reported on their own. Each value has a 95% confidence interval from a bootstrap over images: 10,000 resamples
of the images drawn with numpy's default_rng(0), the same resamples for every value of a group, and the 2.5th and
97.5th percentiles. Resamples that hold no face of a breakdown are left out of its interval and counted in
resamplesWithNoFaces. Each transform and setting (inputSize and tiling) in the run is scored on its own.

The miss rate is broken down by face size, occlusion, truncation and yaw (once labelled), and, when
eval/manifest/luma.csv exists (face_luma.py), into the darkest tenth of the faces by mean luma, the ceil(n / 10)
faces with the lowest, ties broken by image and face ID, and the rest.

--operating-point applies the protocol's rule on the tune split, with no transform, for each setting: for each
threshold from 0.05 to 0.99 in steps of 0.01, take the smallest pad from 0 to 1 in steps of 0.05 at which at least
99% of the found faces are covered completely; the operating point is the lowest threshold at which, with its
pad, false masks stay at or below 0.25 per image.

The summary is JSON, printed or written to --out. --faces writes one CSV row per face, for further breakdowns.
"""
import argparse, csv, json, math, sys
from pathlib import Path
import numpy as np
import download
import face_luma
import transforms

ROOT = Path(__file__).resolve().parents[1]
PROTECTED, COMPLETE, MATCH_IOU, FALSE_IOU = 0.9, 1 - 1e-9, 0.5, 0.1
RESAMPLES, SEED = 10_000, 0
PADS = [k / 20 for k in range(21)]               # 0 to 1 in steps of 0.05
THRESHOLDS = [k / 100 for k in range(5, 100)]    # 0.05 to 0.99 in steps of 0.01
COMPLETE_SHARE, FALSE_PER_IMAGE = 0.99, 0.25     # the operating-point rule
SIZE_BINS = [(0.02, '<2%'), (0.05, '2-5%'), (0.10, '5-10%'), (0.25, '10-25%'), (math.inf, '>=25%')]
FACE_FIELDS = ['imageId', 'faceId', 'split', 'transform', 'inputSize', 'tiling', 'isDepiction', 'isOccluded',
               'isTruncated', 'yaw', 'size', 'luma', 'darkestTenth', 'coverage', 'protected', 'complete', 'found']


# Geometry. A polygon is a list of (x, y) vertices of a convex shape; a rectangle is (x0, y0, x1, y1).

def area(polygon):
    return abs(sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(polygon, polygon[1:] + polygon[:1]))) / 2


def clip_area(polygon, x0, y0, x1, y1):
    """Area of the part of the convex polygon inside the rectangle [x0, x1] × [y0, y1] (Sutherland-Hodgman)."""
    for axis, bound, keep_above in ((0, x0, True), (0, x1, False), (1, y0, True), (1, y1, False)):
        inside = (lambda p: p[axis] >= bound) if keep_above else (lambda p: p[axis] <= bound)
        clipped = []
        for p, q in zip(polygon, polygon[1:] + polygon[:1]):
            if inside(p):
                clipped.append(p)
            if inside(p) != inside(q):
                t = (bound - p[axis]) / (q[axis] - p[axis])
                clipped.append((p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1])))
        polygon = clipped
        if len(polygon) < 3:
            return 0.0
    return area(polygon)


def covered_area(polygon, masks):
    """Area of the polygon covered by the union of the rectangles masks, which may overlap: the union is cut into
    disjoint cells along the masks' edges, and the polygon is clipped to each covered cell."""
    px = [p[0] for p in polygon]
    py = [p[1] for p in polygon]
    near = [m for m in masks if m[0] < max(px) and m[2] > min(px) and m[1] < max(py) and m[3] > min(py)]
    xs = sorted({v for m in near for v in (m[0], m[2])})
    ys = sorted({v for m in near for v in (m[1], m[3])})
    total = 0.0
    for xa, xb in zip(xs, xs[1:]):
        for ya, yb in zip(ys, ys[1:]):
            if any(m[0] <= xa and xb <= m[2] and m[1] <= ya and yb <= m[3] for m in near):
                total += clip_area(polygon, xa, ya, xb, yb)
    return total


def iou(rect, polygon, polygon_area):
    x0, y0, x1, y1 = rect
    inter = clip_area(polygon, x0, y0, x1, y1)
    union = (x1 - x0) * (y1 - y0) + polygon_area - inter
    return inter / union if union > 0 else 0.0


def mask(box, pad, width, height):
    """The pixels painted for one box: grown by pad, rounded outward to whole pixels, clipped. None if empty."""
    x, y, w, h = box[:4]
    rect = (max(0, math.floor(x - pad * w)), max(0, math.floor(y - pad * h)),
            min(width, math.ceil(x + w + pad * w)), min(height, math.ceil(y + h + pad * h)))
    return rect if rect[2] > rect[0] and rect[3] > rect[1] else None


class Case:
    """One image under one transform and setting: its faces and its detected boxes."""

    def __init__(self, image_id, split, width, height, faces, transform, boxes):
        kind, value = transforms.parse(transform)
        degrees = value if kind == 'rot' else 0
        self.id, self.split = image_id, split
        self.width, self.height = transforms.rotated_size(width, height, degrees)
        self.faces = faces
        self.polygons = [transforms.rotate_points([(f['x'], f['y']), (f['x'] + f['w'], f['y']),
                                                   (f['x'] + f['w'], f['y'] + f['h']), (f['x'], f['y'] + f['h'])],
                                                  width, height, degrees) for f in faces]
        self.areas = [area(p) for p in self.polygons]
        self.boxes = sorted(boxes, key=lambda b: -b[4])  # by score, highest first; sort is stable for ties

    def kept(self, threshold):
        return [b for b in self.boxes if b[4] >= threshold]

    def found(self, threshold):
        """Faces matched one to one by boxes at or above the threshold, before padding and clipped to the image,
        at IoU >= 0.5."""
        found = set()
        for x, y, w, h, _ in self.kept(threshold):
            rect = (max(0.0, x), max(0.0, y), min(self.width, x + w), min(self.height, y + h))
            if rect[2] <= rect[0] or rect[3] <= rect[1]:
                continue
            best, best_iou = None, 0.0
            for k, polygon in enumerate(self.polygons):
                if k not in found and (v := iou(rect, polygon, self.areas[k])) >= MATCH_IOU and v > best_iou:
                    best, best_iou = k, v
            if best is not None:
                found.add(best)
        return found

    def masks(self, pad, threshold):
        return [m for b in self.kept(threshold) if (m := mask(b, pad, self.width, self.height))]

    def coverage(self, masks, faces=None):
        return {k: covered_area(self.polygons[k], masks) / self.areas[k]
                for k in (range(len(self.faces)) if faces is None else faces)}

    def false_masks(self, masks):
        return sum(all(iou(m, p, a) < FALSE_IOU for p, a in zip(self.polygons, self.areas)) for m in masks)


# Loading.

def size_bin(face, width, height):
    share = face['h'] / max(width, height)
    return next(label for limit, label in SIZE_BINS if share < limit)


def load_manifest(folder):
    """(images by ID, faces by image ID). Each face has its size bin, and its mean luma when luma.csv exists."""
    with open(folder / 'images.csv', newline='', encoding='utf-8') as fh:
        images = {r['imageId']: r for r in csv.DictReader(fh)}
    faces = {i: [] for i in images}
    with open(folder / 'faces.csv', newline='', encoding='utf-8') as fh:
        for r in csv.DictReader(fh):
            image = images[r['imageId']]
            face = {**r, **{k: float(r[k]) for k in 'xywh'}}
            face['size'] = size_bin(face, int(image['width']), int(image['height']))
            faces[r['imageId']].append(face)
    luma = face_luma.read_luma(folder / 'luma.csv') if (folder / 'luma.csv').exists() else {}
    keys = {(f['imageId'], f['faceId']) for image_faces in faces.values() for f in image_faces}
    if (folder / 'luma.csv').exists() and set(luma) != keys:
        sys.exit(f'{folder / "luma.csv"} does not match faces.csv; run eval/face_luma.py')
    for image_faces in faces.values():
        for f in image_faces:
            f['luma'] = luma.get((f['imageId'], f['faceId']))
    return images, faces


def setting_of(line):
    return json.dumps({'inputSize': line['inputSize'], 'tiling': line['tiling']}, sort_keys=True)


def load_detections(path, images, faces):
    """(run line, {(transform, setting): [Case]}) from a detections file."""
    with open(path, encoding='utf-8') as fh:
        lines = [json.loads(line) for line in fh if line.strip()]
    if not lines or 'run' not in lines[0]:
        sys.exit(f'{path}: the first line must describe the run (docs/contracts.md, section 4)')
    groups, seen = {}, set()
    for n, line in enumerate(lines[1:], start=2):
        i, transform, setting = line['imageId'], line['transform'], setting_of(line)
        if i not in images:
            sys.exit(f'{path}, line {n}: image {i} is not in the manifest')
        if (i, transform, setting) in seen:
            sys.exit(f'{path}, line {n}: a second line for image {i}, {transform}, {setting}')
        seen.add((i, transform, setting))
        image = images[i]
        boxes = [tuple(float(v) for v in b) for b in line['boxes']]
        if any(len(b) != 5 for b in boxes):
            sys.exit(f'{path}, line {n}: every box must be [x, y, w, h, score]')
        try:
            case = Case(i, image['split'], int(image['width']), int(image['height']), faces[i], transform, boxes)
        except ValueError as e:
            sys.exit(f'{path}, line {n}: {e}')
        groups.setdefault((transform, setting), []).append(case)
    return lines[0], groups


# Statistics.

class Bootstrap:
    """Ratio estimates with percentile intervals from one set of resamples of the images."""

    def __init__(self, n_images):
        draws = np.random.default_rng(SEED).integers(0, n_images, size=(RESAMPLES, n_images)) if n_images else None
        # How often each resample draws each image, so that a resample's sum is one matrix product.
        self.counts = None if draws is None else np.stack([np.bincount(d, minlength=n_images) for d in draws])

    def ratio(self, numerator, denominator):
        num, den = np.asarray(numerator, float), np.asarray(denominator, float)
        result = {'value': float(num.sum() / den.sum()) if den.sum() else None, 'count': int(num.sum()),
                  'n': int(den.sum())}
        if self.counts is not None and den.sum():
            n, d = self.counts @ num, self.counts @ den
            ratios = n[d > 0] / d[d > 0]
            result['low'], result['high'] = (float(v) for v in np.percentile(ratios, [2.5, 97.5]))
            if (d == 0).any():
                result['resamplesWithNoFaces'] = int((d == 0).sum())
        return result


def score_group(images, pad, threshold):
    """Per-face rows and the summary of one transform and setting."""
    rows, per_image = [], []
    for im in images:
        masks = im.masks(pad, threshold)
        found = im.found(threshold)
        coverage = im.coverage(masks)
        per_image.append(im.false_masks(masks))
        for k, face in enumerate(im.faces):
            rows.append({'imageId': im.id, 'faceId': face['faceId'], 'split': im.split,
                         'isDepiction': face['isDepiction'], 'isOccluded': face['isOccluded'],
                         'isTruncated': face['isTruncated'], 'yaw': face['yaw'], 'size': face['size'],
                         'luma': face['luma'], 'coverage': coverage[k], 'protected': coverage[k] >= PROTECTED,
                         'complete': coverage[k] >= COMPLETE, 'found': k in found})
    index = {im.id: n for n, im in enumerate(images)}
    boot = Bootstrap(len(images))

    def per_image_counts(selected, key):
        num, den = np.zeros(len(images)), np.zeros(len(images))
        for r in selected:
            den[index[r['imageId']]] += 1
            num[index[r['imageId']]] += key(r)
        return num, den

    real = [r for r in rows if r['isDepiction'] != '1']
    depictions = [r for r in rows if r['isDepiction'] == '1']
    missed = lambda r: not r['protected']
    summary = {
        'images': len(images), 'faces': len(real), 'depictions': len(depictions),
        'missRate': boot.ratio(*per_image_counts(real, missed)),
        'completeShare': boot.ratio(*per_image_counts(real, lambda r: r['complete'])),
        'recallIoU50': boot.ratio(*per_image_counts(real, lambda r: r['found'])),
        'falseMasksPerImage': boot.ratio(per_image, np.ones(len(images))),
        'depictionMissRate': boot.ratio(*per_image_counts(depictions, missed)),
        'missRateBy': {},
    }
    for field in ('size', 'isOccluded', 'isTruncated', 'yaw'):
        values = ([label for _, label in SIZE_BINS] if field == 'size'
                  else sorted({r[field] for r in real} - {'', 'unclear'}))  # unclear yaw is left out
        summary['missRateBy'][field] = {v: boot.ratio(*per_image_counts([r for r in real if r[field] == v], missed))
                                        for v in values}
    if real and all(r['luma'] is not None for r in real):
        # Measured light: the ceil(n / 10) faces with the lowest mean luma, against the rest.
        ordered = sorted(real, key=lambda r: (r['luma'], r['imageId'], int(r['faceId'])))
        dark = ordered[:math.ceil(len(ordered) / 10)]
        for r in ordered:
            r['darkestTenth'] = False
        for r in dark:
            r['darkestTenth'] = True
        summary['missRateBy']['luma'] = {'darkest tenth': boot.ratio(*per_image_counts(dark, missed)),
                                         'rest': boot.ratio(*per_image_counts(ordered[len(dark):], missed))}
        summary['lumaCutoff'] = dark[-1]['luma']
    return rows, summary


def operating_point(images):
    """(threshold, pad) by the protocol's rule on these images, or None if no threshold meets it."""
    real = {im.id: [k for k, f in enumerate(im.faces) if f['isDepiction'] != '1'] for im in images}
    for threshold in THRESHOLDS:
        found = {im.id: im.found(threshold) & set(real[im.id]) for im in images}
        n_found = sum(map(len, found.values()))
        if not n_found:
            continue
        for pad in PADS:
            complete = sum(c >= COMPLETE for im in images
                           for c in im.coverage(im.masks(pad, threshold), found[im.id]).values())
            if complete >= COMPLETE_SHARE * n_found:
                break
        else:
            continue
        false = sum(im.false_masks(im.masks(pad, threshold)) for im in images)
        if false <= FALSE_PER_IMAGE * len(images):
            return threshold, pad
    return None


def setting_label(setting):
    tiling = setting['tiling']
    name = 'single' if tiling['kind'] == 'none' else f'tiles {tiling["longSide"]}/{tiling["overlap"]}'
    return f'{name} at {setting["inputSize"]} px'


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('detections', type=Path)
    ap.add_argument('--pad', type=float, help='padding as a share of the box size, for example 0.10')
    ap.add_argument('--threshold', type=float, help='score threshold, at least 0.05')
    ap.add_argument('--operating-point', action='store_true', help='find pad and threshold on the tune split')
    ap.add_argument('--split', choices=('tune', 'report', 'all'), help='default: report (tune with --operating-point)')
    ap.add_argument('--manifest', type=Path, default=ROOT / 'eval/manifest')
    ap.add_argument('--out', type=Path, help='write the JSON summary here instead of printing it')
    ap.add_argument('--faces', type=Path, help='write one CSV row per face here')
    args = ap.parse_args(argv)
    if args.operating_point != (args.pad is None and args.threshold is None):
        ap.error('give either --operating-point or both --pad and --threshold')
    if args.operating_point and args.split not in (None, 'tune'):
        ap.error('the operating point is set on the tune split only')

    images, faces = load_manifest(args.manifest)
    run, groups = load_detections(args.detections, images, faces)
    split = 'tune' if args.operating_point else args.split or 'report'
    result = {'run': run, 'detections': str(args.detections), 'detectionsSha256': download.sha256_file(args.detections),
              'manifestSha256': {name: download.sha256_file(args.manifest / name) for name in ('images.csv', 'faces.csv')},
              'split': split, 'groups': []}
    face_rows = []
    for (transform, setting), group in sorted(groups.items()):
        chosen = [im for im in group if split == 'all' or im.split == split]
        expected = sum(split == 'all' or r['split'] == split for r in images.values())
        entry = {'transform': transform, **json.loads(setting), 'imagesInSplit': expected}
        if args.operating_point:
            if transform != 'none':
                continue
            point = operating_point(chosen)
            if point is None:
                entry['operatingPoint'] = None
                result['groups'].append(entry)
                continue
            entry['operatingPoint'] = {'threshold': point[0], 'pad': point[1]}
            threshold, pad = point
        else:
            threshold, pad = args.threshold, args.pad
        rows, summary = score_group(chosen, pad, threshold)
        entry.update({'pad': pad, 'threshold': threshold, **summary})
        result['groups'].append(entry)
        face_rows += [{**r, 'transform': transform, 'inputSize': json.loads(setting)['inputSize'],
                       'tiling': json.dumps(json.loads(setting)['tiling'], sort_keys=True)} for r in rows]

    text = json.dumps(result, indent=1)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + '\n', encoding='utf-8')
    else:
        print(text)
    if args.faces:
        args.faces.parent.mkdir(parents=True, exist_ok=True)
        with open(args.faces, 'w', newline='', encoding='utf-8') as fh:
            writer = csv.DictWriter(fh, FACE_FIELDS, lineterminator='\n')
            writer.writeheader()
            writer.writerows({**r, 'coverage': f'{r["coverage"]:.6f}'} for r in face_rows)
    for g in result['groups']:
        where = f'{g["transform"]}, {setting_label(g)}'
        if 'missRate' not in g:
            print(f'{where}: no operating point meets the rule',
                  file=sys.stderr)
            continue
        m = g['missRate']
        ci = f' [{m["low"]:.4f}, {m["high"]:.4f}]' if 'low' in m else ''
        print(f'{where}: pad {g["pad"]}, threshold {g["threshold"]}, '
              f'{g["images"]} of {g["imagesInSplit"]} {split} images, {g["faces"]} faces, miss rate '
              f'{m["value"] if m["value"] is None else round(m["value"], 4)}{ci}', file=sys.stderr)


if __name__ == '__main__':
    main()
