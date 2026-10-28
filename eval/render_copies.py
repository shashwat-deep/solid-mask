"""Save each test image the way the app saves it, masked and unmasked, for check E3 of docs/eval-protocol.md, part E.

    python eval/render_copies.py results/detections/<run-id>.jsonl --pad 0.10 --threshold 0.50 [--split report]
                                 [--page stub | --page URL]

For each image of the split in the detections file (transform none), the masks are the boxes at or above the
threshold, grown by the padding and rounded outward to whole pixels as score.py and the app do (docs/contracts.md,
section 2). The eval page decodes the image (served as run_detect.py serves it) and its render() (section 3) encodes
two copies exactly as the app saves: one with the masks and one without, the control. They are written to
<out>/<render-id>/<imageId>.masked.jpg and .plain.jpg (through <render-id>.part/ until the last one is
written), with render_info.json: the masks of every image, the
parameters, the SHA-256 of the detections file and of every copy, and the versions. The copies are pictures of the
test images, so they stay in data/, which git ignores. With a real eval page, only images that review.csv keeps are
rendered.
"""
import argparse, base64, datetime, json, platform, sys
from importlib import metadata
from pathlib import Path
import build_manifest
import download
import run_detect
import score

ROOT = Path(__file__).resolve().parents[1]
RENDER = """async ({url, masks}) => {
  const bitmap = await window.solidMask.decode(url);
  const base64 = async (blob) => {
    const bytes = new Uint8Array(await blob.arrayBuffer());
    let text = '';
    for (let i = 0; i < bytes.length; i += 32768) text += String.fromCharCode(...bytes.subarray(i, i + 32768));
    return btoa(text);
  };
  try {
    return {width: bitmap.width, height: bitmap.height,
            masked: await base64(await window.solidMask.render(bitmap, masks)),
            plain: await base64(await window.solidMask.render(bitmap, []))};
  } finally {
    bitmap.close();
  }
}"""


def masks_of(boxes, pad, threshold, width, height):
    """The masks the app paints for these boxes: [x0, y0, x1, y1] in whole pixels."""
    return [list(m) for b in boxes if b[4] >= threshold and (m := score.mask(b, pad, width, height))]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('detections', type=Path)
    ap.add_argument('--pad', type=float, required=True)
    ap.add_argument('--threshold', type=float, required=True)
    ap.add_argument('--split', choices=('tune', 'report', 'all'), default='report')
    ap.add_argument('--page', default='stub', help='"stub" or the URL of the app\'s eval page')
    ap.add_argument('--manifest', type=Path, default=ROOT / 'eval/manifest')
    ap.add_argument('--images', type=Path, default=ROOT / 'data/openimages/images')
    ap.add_argument('--out', type=Path, default=ROOT / 'data/rendered')
    ap.add_argument('--render-id', help='default: the detections file name, the padding and the threshold')
    args = ap.parse_args(argv)
    stub = args.page == 'stub'
    page_url = f'{run_detect.STUB_ORIGIN}/index.html' if stub else args.page

    with open(args.detections, encoding='utf-8') as fh:
        lines = [json.loads(line) for line in fh if line.strip()][1:]
    boxes = {line['imageId']: line['boxes'] for line in lines if line['transform'] == 'none'}
    rows = [r for r in build_manifest.read_csv(args.manifest / 'images.csv')
            if (args.split == 'all' or r['split'] == args.split) and r['imageId'] in boxes]
    if not rows:
        sys.exit(f'{args.detections} has no {args.split} image under transform none')
    files = {r['imageId']: download.image_path(args.images, r['imageId'], r['url']) for r in rows}
    expected = {r['imageId']: r['sha256'] for r in rows}
    bad = [i for i, path in files.items() if not path.exists() or download.sha256_file(path) != expected[i]]
    if bad:
        sys.exit(f'{len(bad)} images are missing or differ from the manifest, for example {bad[0]}; run eval/download.py')
    run_detect.require_review(rows, args.manifest, stub)
    run_detect.check_orientations(rows, files)

    render_id = args.render_id or f'{args.detections.stem}-pad{args.pad}-t{args.threshold}'
    folder = args.out / render_id
    if folder.exists():
        sys.exit(f'{folder} exists; choose another --render-id')
    part = folder.with_name(folder.name + '.part')  # renamed to folder once every copy is written
    if part.exists():
        for leftover in part.iterdir():
            leftover.unlink()
    part.mkdir(parents=True, exist_ok=True)
    images = {}
    with run_detect.EvalPage(page_url, stub) as page:
        for row in rows:
            i, width, height = row['imageId'], int(row['width']), int(row['height'])
            masks = masks_of(boxes[i], args.pad, args.threshold, width, height)
            name, content_type, body, _ = run_detect.prepare(row, files[i], 'none')
            result = page.run(RENDER, name, content_type, body,
                              masks=[{'x': x0, 'y': y0, 'w': x1 - x0, 'h': y1 - y0, 'score': 1} for x0, y0, x1, y1 in masks])
            if (result['width'], result['height']) != (width, height):
                sys.exit(f'{i} decoded at {result["width"]} x {result["height"]}, the manifest says {width} x {height}')
            entry = {'width': width, 'height': height, 'masks': masks}
            for kind in ('masked', 'plain'):
                data = base64.b64decode(result[kind])
                (part / f'{i}.{kind}.jpg').write_bytes(data)
                entry[f'{kind}Sha256'] = run_detect.sha256(data)
            images[i] = entry
    info = {'render': render_id, 'detections': str(args.detections),
            'detectionsSha256': download.sha256_file(args.detections), 'pad': args.pad, 'threshold': args.threshold,
            'split': args.split, 'page': args.page, 'pageInfo': page.info, 'browser': page.version,
            'manifestSha256': download.sha256_file(args.manifest / 'images.csv'), 'images': images,
            'created': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'),
            'gitCommit': run_detect.git_commit(), 'python': platform.python_version(),
            'playwright': metadata.version('playwright')}
    (part / 'render_info.json').write_text(json.dumps(info, indent=1) + '\n', encoding='utf-8')
    part.rename(folder)
    print(f'{len(images)} images, {sum(len(e["masks"]) for e in images.values())} masks: {folder}')


if __name__ == '__main__':
    main()
