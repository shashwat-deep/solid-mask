"""Build the Open Images face test set: eval/manifest/images.csv and eval/manifest/faces.csv.

    python eval/build_manifest.py [--tune 200] [--report 800]

Follows docs/eval-protocol.md, part B, "Data", with the columns of docs/contracts.md, section 6. The script

1. downloads Open Images' image lists and box annotations for its validation and test splits into
   data/openimages/meta/ and checks them against the SHA-256s in META;
2. keeps the images with at least one "Human face" box, no face box marked IsGroupOf, the CC BY 2.0 licence and
   a known orientation (Rotation 0, 90, 180 or 270), and, once downloaded, no EXIF orientation other than 1 in
   the file (the browser would turn the image by it, and Open Images' boxes and Rotation do not say whether they
   allow for it);
3. puts an image in the tune split when the SHA-256 of "solid-mask:split:0:<imageId>", read as a number, is
   divisible by 5, and in the report split otherwise;
4. ranks the images of each split by the SHA-256 of "solid-mask:order:0:<imageId>" and takes the first --tune
   and --report images that the review (eval/manifest/review.csv) has not removed;
5. downloads those images from the copies that CVDF hosts for Open Images into data/openimages/images/, and
   records each file's SHA-256 and the size of the upright image;
6. writes each face box in pixels of the upright image, which is the image as stored turned counterclockwise by
   its Rotation, and copies Open Images' normalised coordinates, which refer to the image as stored.

Run it again after each round of the review: each removed image is replaced by the next one in its split's
ranking. Images already in the manifest must still match their recorded SHA-256s, and yaw labels are kept.
"""
import argparse, csv, hashlib, sys
from pathlib import Path
from PIL import Image
import download
import transforms

ROOT = Path(__file__).resolve().parents[1]
META = {  # file name: (URL, SHA-256 of the copy downloaded on 27 October 2026)
    'validation-images-with-rotation.csv': (
        'https://storage.googleapis.com/openimages/2018_04/validation/validation-images-with-rotation.csv',
        'ed93a0e121fe345effdfc7359b848dbc64a1ff6778c8c73563157cb500b33a17'),
    'test-images-with-rotation.csv': (
        'https://storage.googleapis.com/openimages/2018_04/test/test-images-with-rotation.csv',
        'de55c6b8cbda32a79f4a20f28572d54e9c49d527a4006725675764074a51a36d'),
    'validation-annotations-bbox.csv': (
        'https://storage.googleapis.com/openimages/v5/validation-annotations-bbox.csv',
        'd8bbd59410af14835d7733165a7bb8a3f0213981b22dd5077b0b9f7878991ff2'),
    'test-annotations-bbox.csv': (
        'https://storage.googleapis.com/openimages/v5/test-annotations-bbox.csv',
        'fe22e579b9453875601576859d14ef3304058165de139c66b725e599202bd7b1'),
    'oidv7-class-descriptions-boxable.csv': (
        'https://storage.googleapis.com/openimages/v7/oidv7-class-descriptions-boxable.csv',
        '1839e0e7e84130ae281f7f67413768601b031581c0c42e7fc17527b8e2a99aa9'),
}
CVDF = 'https://open-images-dataset.s3.amazonaws.com/{subset}/{image_id}.jpg'
FACE = '/m/0dzct'
LICENCE = 'https://creativecommons.org/licenses/by/2.0/'
ROTATIONS = {'0.0': 0, '90.0': 90, '180.0': 180, '270.0': 270}  # an empty value means the orientation is unknown
SEED = 0
IMAGE_COLUMNS = ['imageId', 'source', 'split', 'url', 'landingUrl', 'licence', 'author', 'authorUrl', 'title',
                 'sha256', 'width', 'height', 'rotation']
FACE_COLUMNS = ['imageId', 'faceId', 'x', 'y', 'w', 'h', 'xMinNorm', 'xMaxNorm', 'yMinNorm', 'yMaxNorm',
                'isOccluded', 'isTruncated', 'isDepiction', 'yaw']
REVIEW_COLUMNS = ['imageId', 'decision', 'reason', 'reviewer']
REASONS = ('intimate', 'doubtful', 'unboxed-face')


def read_csv(path):
    with open(path, newline='', encoding='utf-8') as fh:
        return list(csv.DictReader(fh))


def write_csv(path, columns, rows):
    with open(path, 'w', newline='', encoding='utf-8') as fh:
        writer = csv.DictWriter(fh, columns, lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)


def digest(kind, image_id):
    return hashlib.sha256(f'solid-mask:{kind}:{SEED}:{image_id}'.encode()).hexdigest()


def split_of(image_id):
    return 'tune' if int(digest('split', image_id), 16) % 5 == 0 else 'report'


def face_boxes(meta):
    """{imageId: [face box rows in file order]} for the validation and test splits."""
    boxes = {}
    for subset in ('validation', 'test'):
        with open(meta / f'{subset}-annotations-bbox.csv', newline='', encoding='utf-8') as fh:
            header = next(csv.reader([fh.readline()]))
            for row in csv.DictReader((line for line in fh if FACE in line), fieldnames=header):
                if row['LabelName'] == FACE:
                    boxes.setdefault(row['ImageID'], []).append(row)
    return boxes


def image_info(meta, ids):
    return {row['ImageID']: row for subset in ('validation', 'test')
            for row in read_csv(meta / f'{subset}-images-with-rotation.csv') if row['ImageID'] in ids}


def eligible(boxes, info):
    """Images that pass the protocol's exclusions other than the review, sorted by ID."""
    return sorted(i for i, faces in boxes.items()
                  if i in info and all(f['IsGroupOf'] == '0' for f in faces)
                  and info[i]['License'] == LICENCE and info[i]['Rotation'] in ROTATIONS)


def read_review(path):
    """{imageId: 'keep' or 'remove'} from review.csv, after checking every row."""
    review, rows = {}, read_csv(path) if path.exists() else []
    if rows and list(rows[0]) != REVIEW_COLUMNS:
        sys.exit(f'{path}: the columns must be {",".join(REVIEW_COLUMNS)}')
    for line, row in enumerate(rows, start=2):
        valid = ((row['decision'] == 'keep' and not row['reason']) or
                 (row['decision'] == 'remove' and row['reason'] in REASONS))
        if not valid or not row['reviewer'] or row['imageId'] in review:
            sys.exit(f'{path}, line {line}: expected a new imageId, "keep" with no reason or "remove" with one of '
                     f'{", ".join(REASONS)}, and a reviewer')
        review[row['imageId']] = row['decision']
    return review


def select(ids, review, n_tune, n_report):
    """[(imageId, split)]: the first n_tune tune and n_report report images in rank order not removed by review."""
    chosen = []
    for split, n in (('tune', n_tune), ('report', n_report)):
        ranked = sorted((i for i in ids if split_of(i) == split), key=lambda i: digest('order', i))
        kept = [i for i in ranked if review.get(i) != 'remove'][:n]
        if len(kept) < n:
            sys.exit(f'only {len(kept)} {split} images are left after the review, {n} wanted')
        chosen += [(i, split) for i in kept]
    return chosen


def upright(x_min, x_max, y_min, y_max, rotation):
    """Normalised box in the image as stored -> the same box once the image is turned counterclockwise."""
    if rotation == 0:
        return x_min, x_max, y_min, y_max
    if rotation == 90:
        return y_min, y_max, 1 - x_max, 1 - x_min
    if rotation == 180:
        return 1 - x_max, 1 - x_min, 1 - y_max, 1 - y_min
    if rotation == 270:
        return 1 - y_max, 1 - y_min, x_min, x_max
    raise ValueError(f'rotation {rotation}')


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--tune', type=int, default=200, help='images in the tune split')
    ap.add_argument('--report', type=int, default=800, help='images in the report split')
    ap.add_argument('--meta', type=Path, default=ROOT / 'data/openimages/meta')
    ap.add_argument('--images', type=Path, default=ROOT / 'data/openimages/images')
    ap.add_argument('--manifest', type=Path, default=ROOT / 'eval/manifest')
    ap.add_argument('--jobs', type=int, default=8, help='parallel downloads')
    args = ap.parse_args(argv)

    _, failed = download.fetch_all([(name, url, args.meta / name, sha) for name, (url, sha) in META.items()])
    if failed:
        sys.exit('\n'.join(f'{name}: {error}' for name, error in sorted(failed.items())))
    with open(args.meta / 'oidv7-class-descriptions-boxable.csv', newline='', encoding='utf-8') as fh:
        if dict(csv.reader(fh)).get(FACE) != 'Human face':
            sys.exit(f'{FACE} is not "Human face" in oidv7-class-descriptions-boxable.csv')
    boxes = face_boxes(args.meta)
    info = image_info(args.meta, boxes)
    ids = eligible(boxes, info)
    review = read_review(args.manifest / 'review.csv')

    old_images = args.manifest / 'images.csv'
    known = {r['imageId']: r['sha256'] for r in read_csv(old_images)} if old_images.exists() else {}
    old_faces = args.manifest / 'faces.csv'
    old_yaw = {(r['imageId'], r['faceId']): r['yaw'] for r in read_csv(old_faces)} if old_faces.exists() else {}
    url = {i: CVDF.format(subset=info[i]['Subset'], image_id=i) for i in ids}
    path = {i: download.image_path(args.images, i, url[i]) for i in ids}
    oriented = set()  # files with an EXIF orientation other than 1
    while True:  # each image left out is replaced by the next one in its split's ranking, which is checked in turn
        chosen = select([i for i in ids if i not in oriented], review, args.tune, args.report)
        sha, failed = download.fetch_all([(i, url[i], path[i], known.get(i)) for i, _ in chosen], args.jobs)
        if failed:
            sys.exit('\n'.join(f'{i}: {error}' for i, error in sorted(failed.items())))
        known.update(sha)
        found = {i for i, _ in chosen if transforms.exif_orientation(path[i]) not in (None, 1)}
        if not found:
            break
        oriented |= found

    image_rows, face_rows, large, with_exif, with_icc = [], [], 0, 0, 0
    for i, split in sorted(chosen):
        meta, rotation = info[i], ROTATIONS[info[i]['Rotation']]
        with Image.open(path[i]) as im:
            im.load()  # decodes the whole file, so a damaged image stops the script here
            width, height = im.size if rotation in (0, 180) else im.size[::-1]
            large += max(im.size) > 1024
            with_exif += bool(im.info.get('exif'))
            with_icc += bool(im.info.get('icc_profile'))
        image_rows.append({
            'imageId': i, 'source': f'openimages-v7-{meta["Subset"]}', 'split': split, 'url': url[i],
            'landingUrl': meta['OriginalLandingURL'], 'licence': meta['License'], 'author': meta['Author'],
            'authorUrl': meta['AuthorProfileURL'], 'title': meta['Title'], 'sha256': sha[i],
            'width': width, 'height': height, 'rotation': rotation})
        for n, face in enumerate(boxes[i]):
            x0, x1, y0, y1 = upright(*(float(face[k]) for k in ('XMin', 'XMax', 'YMin', 'YMax')), rotation)
            face_rows.append({
                'imageId': i, 'faceId': n, 'x': f'{x0 * width:.3f}', 'y': f'{y0 * height:.3f}',
                'w': f'{(x1 - x0) * width:.3f}', 'h': f'{(y1 - y0) * height:.3f}',
                'xMinNorm': face['XMin'], 'xMaxNorm': face['XMax'], 'yMinNorm': face['YMin'],
                'yMaxNorm': face['YMax'], 'isOccluded': face['IsOccluded'], 'isTruncated': face['IsTruncated'],
                'isDepiction': face['IsDepiction'], 'yaw': old_yaw.get((i, str(n)), '')})
    args.manifest.mkdir(parents=True, exist_ok=True)
    write_csv(args.manifest / 'images.csv', IMAGE_COLUMNS, image_rows)
    write_csv(args.manifest / 'faces.csv', FACE_COLUMNS, face_rows)
    if not (args.manifest / 'review.csv').exists():
        write_csv(args.manifest / 'review.csv', REVIEW_COLUMNS, [])

    in_set = {i for i, _ in chosen}
    no_group = [i for i in boxes if i in info and all(f['IsGroupOf'] == '0' for f in boxes[i])]
    unknown = [i for i in no_group if info[i]['Rotation'] not in ROTATIONS]
    print(f'{len(boxes)} validation and test images have a face box, {len(boxes) - len(info)} of them missing '
          f'from the image lists; {len(no_group)} have no group-of face box; {len(unknown)} of these have no '
          f'orientation, {sum("," in info[i]["Title"] for i in unknown)} of them with a comma in the title; '
          f'{len(no_group) - len(unknown) - len(ids)} have another licence')
    print(f'{len(ids)} images are eligible: {sum(split_of(i) == "tune" for i in ids)} tune, '
          f'{sum(split_of(i) == "report" for i in ids)} report')
    print(f'manifest: {args.tune} tune and {args.report} report images with {len(face_rows)} faces, '
          f'{sum(r["isDepiction"] == "1" for r in face_rows)} of them depictions; '
          f'{sum(r["rotation"] != 0 for r in image_rows)} images are stored turned and are rotated upright')
    print(f'files: {large} larger than 1,024 px on the long side, {with_exif} with EXIF data, {with_icc} with an ICC '
          f'profile; {len(oriented)} left out for an EXIF orientation other than 1')
    print(f'review: {sum(d == "keep" for i, d in review.items() if i in in_set)} kept, '
          f'{sum(d == "remove" for d in review.values())} removed, '
          f'{sum(i not in review for i in in_set)} images in the manifest still to review')


if __name__ == '__main__':
    main()
