"""How far is each saved copy from its original under PDQ and pHash: check E3 of docs/eval-protocol.md, part E.

    python eval/hash_distance.py data/rendered/<render-id> [--out results/privacy/e3-<render-id>.json]

For each image that render_copies.py saved, hashes three pictures: the original as Chromium shows it
(transforms.upright()), the masked copy, and the plain copy, re-encoded without masks as the control. It uses PDQ
(pdq.py, 256 bits) and pHash (imagehash.phash, 64 bits), and reports:

- the share of masked copies within PDQ distance 31 of their original, the matching threshold Meta recommends, with
  a 95% bootstrap interval over images (score.Bootstrap), overall and by the share of the picture that is masked;
- the same for the plain copies;
- the full distributions of both distances, for both kinds of copy;
- how many originals have a PDQ quality of 49 or less, which Meta recommends discarding.

The JSON summary goes to --out (by default results/privacy/e3-<render-id>.json, or next to a stub's copies, which
never go into results/), with one row per image in a CSV beside it, the versions and the SHA-256 of
render_info.json. Neither file holds pixels or hashes, only distances, qualities and shares.
"""
import argparse, csv, json, math, statistics, sys
from importlib import metadata
from pathlib import Path
import imagehash
import numpy as np
from PIL import Image
import build_manifest
import download
import pdq
import score
import transforms

ROOT = Path(__file__).resolve().parents[1]
MASKED_BINS = [(0.0, 'no mask'), (0.01, 'under 1%'), (0.05, '1-5%'), (0.10, '5-10%'), (0.25, '10-25%'),
               (math.inf, '25% and over')]
ROW_FIELDS = ['imageId', 'maskedShare', 'maskedBin', 'pdqQuality', 'pdqMasked', 'pdqPlain', 'phashMasked',
              'phashPlain']


def masked_share(masks, width, height):
    """Share of the picture under the union of the masks ([x0, y0, x1, y1] in whole pixels)."""
    frame = [(0, 0), (width, 0), (width, height), (0, height)]
    return score.covered_area(frame, [tuple(m) for m in masks]) / (width * height)


def masked_bin(share):
    if share == 0:
        return MASKED_BINS[0][1]
    return next(label for limit, label in MASKED_BINS[1:] if share < limit)


def hashes(image):
    return pdq.hash_image(image), imagehash.phash(image.convert('RGB'))


def summary(rows):
    """The protocol's numbers for a list of per-image rows."""
    boot = score.Bootstrap(len(rows))
    ones = np.ones(len(rows))
    result = {'images': len(rows)}
    for kind in ('Masked', 'Plain'):
        within = np.array([r[f'pdq{kind}'] <= pdq.MATCH_DISTANCE for r in rows], dtype=float)
        result[f'withinPdq31{kind}'] = boot.ratio(within, ones)
        result[f'withinPdq31{kind}By'] = {
            label: boot.ratio(within * in_bin, in_bin)
            for label, in_bin in ((label, np.array([r['maskedBin'] == label for r in rows], dtype=float))
                                  for _, label in MASKED_BINS)}
        for name in ('pdq', 'phash'):
            values = sorted(r[f'{name}{kind}'] for r in rows)
            result[f'{name}{kind}'] = {
                'median': statistics.median(values) if values else None,
                'quartiles': statistics.quantiles(values, n=4) if len(values) > 1 else None,
                'histogram': {str(d): values.count(d) for d in sorted(set(values))}}
    result['lowQualityOriginals'] = sum(r['pdqQuality'] < pdq.MIN_QUALITY for r in rows)
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('rendered', type=Path, help='a folder written by render_copies.py')
    ap.add_argument('--manifest', type=Path, default=ROOT / 'eval/manifest')
    ap.add_argument('--images', type=Path, default=ROOT / 'data/openimages/images')
    ap.add_argument('--out', type=Path)
    args = ap.parse_args(argv)
    info = json.loads((args.rendered / 'render_info.json').read_text(encoding='utf-8'))
    stub = info['page'] == 'stub'
    out = args.out or (args.rendered / 'e3.json' if stub else ROOT / f'results/privacy/e3-{info["render"]}.json')
    if stub and (ROOT / 'results') in [out.resolve(), *out.resolve().parents]:
        ap.error('copies rendered by the stub measure nothing, so their report never goes into results/')

    manifest = {r['imageId']: r for r in build_manifest.read_csv(args.manifest / 'images.csv')}
    rows = []
    for i, entry in sorted(info['images'].items()):
        row = manifest[i]
        path = download.image_path(args.images, i, row['url'])
        if download.sha256_file(path) != row['sha256']:
            sys.exit(f'{path} differs from the manifest; run eval/download.py')
        for kind in ('masked', 'plain'):
            if download.sha256_file(args.rendered / f'{i}.{kind}.jpg') != entry[f'{kind}Sha256']:
                sys.exit(f'{args.rendered / f"{i}.{kind}.jpg"} differs from render_info.json')
        (pdq_original, quality), phash_original = hashes(transforms.upright(path, int(row['rotation'])))
        record = {'imageId': i, 'pdqQuality': quality}
        for kind in ('masked', 'plain'):
            with Image.open(args.rendered / f'{i}.{kind}.jpg') as copy:
                (pdq_copy, _), phash_copy = hashes(copy)
            record[f'pdq{kind.title()}'] = pdq.distance(pdq_original, pdq_copy)
            record[f'phash{kind.title()}'] = phash_original - phash_copy
        share = masked_share(entry['masks'], entry['width'], entry['height'])
        record.update({'maskedShare': round(share, 6), 'maskedBin': masked_bin(share)})
        rows.append(record)

    report = {'render': info['render'], 'renderInfoSha256': download.sha256_file(args.rendered / 'render_info.json'),
              'pad': info['pad'], 'threshold': info['threshold'], 'split': info['split'],
              'pdqMatchDistance': pdq.MATCH_DISTANCE, 'pdqMinQuality': pdq.MIN_QUALITY, **summary(rows),
              'versions': {name: metadata.version(name) for name in ('ImageHash', 'numpy', 'pillow', 'scipy')}}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1) + '\n', encoding='utf-8')
    with open(out.with_suffix('.csv'), 'w', newline='', encoding='utf-8') as fh:
        writer = csv.DictWriter(fh, ROW_FIELDS, lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)
    masked = report['withinPdq31Masked']
    print(f'{len(rows)} images: {masked["count"]} masked copies within PDQ distance {pdq.MATCH_DISTANCE} of their '
          f'original ({masked["value"]:.3f}); plain copies: {report["withinPdq31Plain"]["count"]}. {out}')


if __name__ == '__main__':
    main()
