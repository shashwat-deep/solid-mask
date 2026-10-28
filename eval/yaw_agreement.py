"""Compare two authors' yaw labels: Cohen's kappa, the confusion table, and the faces to settle together.

    python eval/yaw_agreement.py [--labellers shashwat pratyush] [--write]

Reads results/yaw/yaw-<labeller>.csv for both authors: the files yaw_sheet.py's page makes, which stay in data/yaw/
until both authors have finished and are then committed together under results/yaw/. Each must label every face of
the current sample. Labels of faces outside it are counted and left out.
Reports Cohen's kappa over the four labels, with a 95% confidence interval from the bootstrap over images that
score.py uses (10,000 resamples of the images, numpy's default_rng(0), percentile interval); kappa over the faces
neither author called unclear; the observed agreement; each author's counts; and the confusion table. Writes the
faces they disagree on to results/yaw/yaw-disagreements.csv, with a column of labels named after each author (in
alphabetical order) and a `settled` column, keeping any settled labels already filled in. The summary goes to
results/yaw/agreement.json (--out), with the SHA-256 of both label files, of the disagreements file and of
images.csv and faces.csv as read, the git commit, and the versions of Python and numpy. Once the authors have
filled the `settled` column together, --write puts the final labels into the yaw column of
eval/manifest/faces.csv: the shared label where they agree, the settled one where they did not.
"""
import argparse, json, platform, sys
from pathlib import Path
import numpy as np
import build_manifest
import download
import run_detect
import score
import yaw_sheet

ROOT = Path(__file__).resolve().parents[1]


def kappa(table):
    """Cohen's kappa of a square table of counts (rows: one rater, columns: the other); None if undefined."""
    table = np.asarray(table, dtype=float)
    n = table.sum()
    if n == 0:
        return None
    observed = np.trace(table) / n
    expected = (table.sum(axis=1) @ table.sum(axis=0)) / n ** 2
    return None if expected == 1 else float((observed - expected) / (1 - expected))


def kappa_interval(per_image):
    """kappa with its 95% bootstrap interval, from one table per image (an array of shape images x k x k)."""
    per_image = np.asarray(per_image, dtype=float)
    result = {'value': kappa(per_image.sum(axis=0)), 'faces': int(per_image.sum())}
    boot = score.Bootstrap(len(per_image))
    if boot.counts is None or result['value'] is None:
        return result
    k = per_image.shape[1]
    tables = (boot.counts @ per_image.reshape(len(per_image), -1)).reshape(-1, k, k)
    n = tables.sum(axis=(1, 2))
    observed = np.trace(tables, axis1=1, axis2=2) / n
    expected = np.einsum('bi,bi->b', tables.sum(axis=2), tables.sum(axis=1)) / n ** 2
    defined = expected < 1
    values = (observed[defined] - expected[defined]) / (1 - expected[defined])
    result['low'], result['high'] = (float(v) for v in np.percentile(values, [2.5, 97.5]))
    if (~defined).any():
        result['resamplesUndefined'] = int((~defined).sum())
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--labellers', nargs=2, default=['shashwat', 'pratyush'])
    ap.add_argument('--manifest', type=Path, default=ROOT / 'eval/manifest')
    ap.add_argument('--labels', type=Path, default=ROOT / 'results/yaw')
    ap.add_argument('--out', type=Path, help='where the JSON summary goes (default: agreement.json beside the labels)')
    ap.add_argument('--write', action='store_true', help='put the final labels into faces.csv')
    args = ap.parse_args(argv)

    manifest_sha = {name: download.sha256_file(args.manifest / name) for name in ('images.csv', 'faces.csv')}
    images = {r['imageId']: r for r in build_manifest.read_csv(args.manifest / 'images.csv')}
    faces = build_manifest.read_csv(args.manifest / 'faces.csv')
    chosen = [(f['imageId'], f['faceId']) for f in yaw_sheet.sample(images, faces)]
    first, second = (yaw_sheet.read_labels(args.labels / f'yaw-{name}.csv') for name in args.labellers)
    outside = {}
    for name, labels in zip(args.labellers, (first, second)):
        missing = set(chosen) - set(labels)
        if missing:
            sys.exit(f'{name} has {len(missing)} faces of the sample unlabelled; run yaw_sheet.py --labeller {name}')
        outside[name] = len(set(labels) - set(chosen))

    index = {label: k for k, label in enumerate(yaw_sheet.LABELS)}
    image_ids = sorted({i for i, _ in chosen})
    row_of = {i: r for r, i in enumerate(image_ids)}
    per_image = np.zeros((len(image_ids), len(index), len(index)))
    for face in chosen:
        per_image[row_of[face[0]], index[first[face]], index[second[face]]] += 1
    clear = [index[label] for label in yaw_sheet.LABELS if label != 'unclear']
    total = per_image.sum(axis=0)
    summary = {
        'labellers': args.labellers, 'faces': len(chosen), 'images': len(image_ids), 'labelsOutsideSample': outside,
        'kappa': kappa_interval(per_image),
        'kappaWithoutUnclear': kappa_interval(per_image[:, clear][:, :, clear]),
        'observedAgreement': float(np.trace(total) / total.sum()),
        'counts': {name: {label: int(total.sum(axis=1 - side)[index[label]]) for label in yaw_sheet.LABELS}
                   for side, name in enumerate(args.labellers)},
        'confusion': {a: {b: int(total[index[a], index[b]]) for b in yaw_sheet.LABELS} for a in yaw_sheet.LABELS},
    }

    path = args.labels / 'yaw-disagreements.csv'
    settled = {(r['imageId'], r['faceId']): r['settled'] for r in build_manifest.read_csv(path)} if path.exists() else {}
    by_name = dict(zip(args.labellers, (first, second)))
    names = sorted(args.labellers)
    rows = [{'imageId': i, 'faceId': n, **{name: by_name[name][(i, n)] for name in names},
             'settled': settled.get((i, n), '')} for i, n in sorted(chosen) if first[(i, n)] != second[(i, n)]]
    bad = [r for r in rows if r['settled'] not in ('', *yaw_sheet.LABELS)]
    if bad:
        sys.exit(f'{path}: settled must be one of {", ".join(yaw_sheet.LABELS)}, for example {bad[0]["imageId"]}')
    build_manifest.write_csv(path, ['imageId', 'faceId', *names, 'settled'], rows)
    summary['disagreements'] = len(rows)
    summary['unsettled'] = sum(not r['settled'] for r in rows)
    summary.update({
        'labelsSha256': {name: download.sha256_file(args.labels / f'yaw-{name}.csv') for name in args.labellers},
        'disagreementsSha256': download.sha256_file(path), 'manifestSha256': manifest_sha,
        'gitCommit': run_detect.git_commit(), 'python': platform.python_version(), 'numpy': np.__version__})

    text = json.dumps(summary, indent=1)
    out = args.out or args.labels / 'agreement.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text + '\n', encoding='utf-8')
    print(text)

    if args.write:
        if summary['unsettled']:
            sys.exit(f'{summary["unsettled"]} disagreements in {path} are not settled yet')
        final = {face: first[face] for face in chosen}
        final.update({(r['imageId'], r['faceId']): r['settled'] for r in rows})
        for face in faces:
            face['yaw'] = final.get((face['imageId'], face['faceId']), '')
        build_manifest.write_csv(args.manifest / 'faces.csv', build_manifest.FACE_COLUMNS, faces)
        print(f'wrote the yaw of {len(final)} faces into {args.manifest / "faces.csv"}', file=sys.stderr)


if __name__ == '__main__':
    main()
