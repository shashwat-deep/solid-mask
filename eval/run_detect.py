"""Run the face detector on the test images in headless Chromium and write a detections file.

    python eval/run_detect.py [--page stub | --page URL] [--split report] [--limit N] [--tiles 1920,0.25]
                              [--transforms none,rot15,dark2]

Follows docs/contracts.md, sections 3 and 4. Playwright opens the eval page in headless Chromium and calls its
window.solidMask.decode() and detectFaces() for each image, so the boxes come from the shipped decoding,
preprocessing and inference. --page takes the address of the app's eval page (app/eval.html, served by the app's
development server). Until that page exists, the default, --page stub, uses eval/stub/: a stand-in with the same
interface whose "detector" finds solid magenta rectangles, for testing this script.

The runner serves each test image to the page itself, from data/, on the page's own origin under /__eval__/images/,
so the page's content security policy (connect-src 'self') allows the fetch. Every request to another origin is
refused, and the run stops. An image that Open Images stores turned (Rotation 90, 180 or 270) is served with an
EXIF orientation tag added, so the page's createImageBitmap(..., {imageOrientation: "from-image"}) turns it upright
as it does a phone photo; the runner checks each decoded size against the upright size in the manifest. Before it
starts, it checks every image file against its SHA-256 in the manifest, and, unless the page is the stub, that
review.csv keeps every image: part B runs no detector on an image before it is reviewed.

--transforms lists the transforms to run, each over every image: none, rot<degrees> and dark<EV>
(docs/eval-protocol.md, part B, "Breakdowns"). The runner makes each rotated or darkened image with
eval/transforms.py just before the page asks for it, as a PNG, and keeps none of them.

Writes <out>/<run-id>.jsonl (out is results/detections, or data/stub-runs for the stub, which is never written
into results/): the run line, then one line per image with every box scoring 0.05 or more (docs/
contracts.md, section 4). <out>/<run-id>.run_info.json records the versions, hashes, timings, boxesSha256, the
SHA-256 of the lines after the run line, which two runs on the same versions must share, and servedSha256, a
SHA-256 over every image served, which tells whether two runs gave the page the same images. The lines follow the
manifest, each image with its transforms in the order of --transforms. A run that stops early leaves only
<run-id>.jsonl.part.
"""
import argparse, datetime, hashlib, json, platform, statistics, subprocess, sys, time
from importlib import metadata
from pathlib import Path
from urllib.parse import urlsplit
from PIL import features
import build_manifest
import download
import transforms

ROOT = Path(__file__).resolve().parents[1]
STUB = Path(__file__).resolve().parent / 'stub'
STUB_ORIGIN = 'http://eval.localhost'
IMAGE_PATH = '/__eval__/images/'
RUNNER_THRESHOLD = 0.05                              # docs/contracts.md, section 1
NMS_IOU = {'yunet': 0.3, 'yolo5face': 0.5}           # OpenCV's default for YuNet; yolov5-face's default
EXIF_ORIENTATION = {90: 8, 180: 3, 270: 6}           # Open Images' counterclockwise Rotation -> EXIF Orientation
CONTENT_TYPES = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png'}
DETECT = """async ({url, options}) => {
  const bitmap = await window.solidMask.decode(url);
  try {
    const boxes = await window.solidMask.detectFaces(bitmap, options);
    return {width: bitmap.width, height: bitmap.height, boxes: boxes.map(b => [b.x, b.y, b.w, b.h, b.score])};
  } finally {
    bitmap.close();
  }
}"""


def with_orientation(jpeg, rotation):
    """The JPEG with an EXIF segment holding only the Orientation tag that turns it counterclockwise by rotation.

    The segment goes after the start of the file and the JFIF segment, if there is one. A JPEG that already has
    EXIF data is refused, since it could hold an orientation of its own."""
    if rotation == 0:
        return jpeg
    if jpeg[:2] != b'\xff\xd8':
        raise ValueError('not a JPEG file')
    at, insert_at = 2, 2
    while at + 1 < len(jpeg) and jpeg[at] == 0xFF:  # the segments before the image data
        marker = jpeg[at + 1]
        if marker == 0xFF:            # a fill byte before a marker
            at += 1
            continue
        if marker in (0xDA, 0xD9):    # start of the image data, or the end of the file
            break
        if marker == 0x01 or 0xD0 <= marker <= 0xD7:  # markers without a length
            at += 2
            continue
        length = int.from_bytes(jpeg[at + 2:at + 4], 'big')
        if marker == 0xE1 and jpeg[at + 4:at + 10] == b'Exif\x00\x00':
            raise ValueError('the JPEG already has EXIF data')
        if marker == 0xE0 and at == 2:
            insert_at = at + 2 + length
        at += 2 + length
    tiff = (b'MM\x00\x2a\x00\x00\x00\x08'                    # big-endian TIFF header, first directory at byte 8
            b'\x00\x01'                                      # one entry:
            b'\x01\x12\x00\x03\x00\x00\x00\x01'              # tag 0x0112 Orientation, type SHORT, count 1,
            + EXIF_ORIENTATION[rotation].to_bytes(2, 'big') + b'\x00\x00'   # value, padding
            + b'\x00\x00\x00\x00')                           # no further directory
    payload = b'Exif\x00\x00' + tiff
    return jpeg[:insert_at] + b'\xff\xe1' + (len(payload) + 2).to_bytes(2, 'big') + payload + jpeg[insert_at:]


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def prepare(row, path, transform, upright=None):
    """(file name, content type, bytes, expected decoded size) of one manifest image under one transform. upright
    is transforms.upright() of the image, if already made."""
    width, height, rotation = int(row['width']), int(row['height']), int(row['rotation'])
    if transform == 'none':
        return (row['imageId'] + path.suffix, CONTENT_TYPES.get(path.suffix.lower()),
                with_orientation(path.read_bytes(), rotation), (width, height))
    kind, value = transforms.parse(transform)
    if upright is None:
        upright = transforms.upright(path, rotation)
    image = transforms.apply(upright, transform, row['imageId'])
    expected = transforms.rotated_size(width, height, value) if kind == 'rot' else (width, height)
    return f'{row["imageId"]}.{transform}.png', 'image/png', transforms.png(image), expected


class EvalPage:
    """Headless Chromium on the eval page, with the runner's routing: each image is served on the page's own origin
    under IMAGE_PATH, the stub's files come from eval/stub/, and a request to any other origin is refused and stops
    the run. Use it as a context manager; run() serves one image and runs a script on it."""

    def __init__(self, page_url, stub):
        self.page_url, self.stub = page_url, stub
        parts = urlsplit(page_url)
        self.origin = f'{parts.scheme}://{parts.netloc}'
        self.blocked, self.pending = [], {}

    def _route(self, request_route):
        url = request_route.request.url
        here = urlsplit(url)
        if f'{here.scheme}://{here.netloc}' != self.origin:
            self.blocked.append(url)
            return request_route.abort('blockedbyclient')
        if here.path.startswith(IMAGE_PATH):
            entry = self.pending.get(here.path[len(IMAGE_PATH):])
            if entry is None:
                return request_route.fulfill(status=404)
            return request_route.fulfill(status=200, content_type=entry[0], body=entry[1])
        if self.stub:
            file = STUB / here.path.lstrip('/')
            if file.parent != STUB or not file.is_file():
                return request_route.fulfill(status=404)
            return request_route.fulfill(path=file)
        return request_route.continue_()

    def _check(self):
        if self.blocked:
            sys.exit(f'the page asked for another origin, so the run stops: {self.blocked[0]}')

    def __enter__(self):
        from playwright.sync_api import sync_playwright
        self._playwright = sync_playwright().start()
        try:
            self.browser = self._playwright.chromium.launch()
            context = self.browser.new_context()
            context.route('**/*', self._route)
            self.page = context.new_page()
            self.page.goto(self.page_url)
            self.page.wait_for_function('() => window.solidMask !== undefined', timeout=120_000)
            self.info = self.page.evaluate('() => window.solidMask.info()')
            self.version = self.browser.version
        except BaseException:
            self._playwright.stop()
            raise
        return self

    def run(self, script, name, content_type, body, **arg):
        """Serve body as the one image the page may fetch, at name, and run script with {url, **arg}."""
        self.pending.clear()
        self.pending[name] = (content_type, body)
        result = self.page.evaluate(script, {'url': f'{self.origin}{IMAGE_PATH}{name}', **arg})
        self._check()
        return result

    def __exit__(self, kind, error, trace):
        try:
            if kind is None:
                self.page.close(run_before_unload=True)  # so a request made while the page unloads is checked too
        finally:
            self.browser.close()
            self._playwright.stop()
        if kind is None:
            self._check()


def check_orientations(rows, files):
    """Fail before the browser starts, not inside it, on an image stored turned that cannot be served upright."""
    for r in rows:
        if int(r['rotation']):
            try:
                with_orientation(files[r['imageId']].read_bytes(), int(r['rotation']))
            except (ValueError, IndexError) as e:
                sys.exit(f'{r["imageId"]}: cannot add an EXIF orientation tag: {e}')


def require_review(rows, manifest, stub):
    """Part B runs no detector on an image before it is reviewed, so a real eval page gets only images that
    review.csv keeps. The stub runs no detector."""
    if stub:
        return
    review = build_manifest.read_review(manifest / 'review.csv')
    unreviewed = [r['imageId'] for r in rows if review.get(r['imageId']) != 'keep']
    if unreviewed:
        sys.exit(f'{len(unreviewed)} images have no "keep" in {manifest / "review.csv"}, for example {unreviewed[0]}; '
                 f'part B of the protocol runs no detector on an image before it is reviewed')


def git_commit():
    try:
        commit = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, text=True,
                                check=True).stdout.strip()
        dirty = subprocess.run(['git', 'status', '--porcelain'], cwd=ROOT, capture_output=True, text=True,
                               check=True).stdout.strip()
        return commit + (' with uncommitted changes' if dirty else '')
    except (OSError, subprocess.CalledProcessError):
        return None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--page', default='stub', help='"stub" or the URL of the app\'s eval page')
    ap.add_argument('--model', choices=sorted(NMS_IOU), default='yunet')
    ap.add_argument('--input-size', type=int, default=640)
    ap.add_argument('--tiles', metavar='LONG_SIDE,OVERLAP', help='the tiled setting, for example 1920,0.25')
    ap.add_argument('--nms-iou', type=float, help='default: 0.3 for yunet, 0.5 for yolo5face')
    ap.add_argument('--transforms', default='none', help='comma-separated: none, rot<degrees>, dark<EV>')
    ap.add_argument('--split', choices=('tune', 'report', 'all'), default='all')
    ap.add_argument('--limit', type=int, help='only the first N images of the split, in manifest order')
    ap.add_argument('--manifest', type=Path, default=ROOT / 'eval/manifest')
    ap.add_argument('--images', type=Path, default=ROOT / 'data/openimages/images')
    ap.add_argument('--out', type=Path, help='default: results/detections, or data/stub-runs for the stub')
    ap.add_argument('--run-id', help='default: <date>-<stub or app>-<model>-<input size>-<setting>')
    args = ap.parse_args(argv)

    stub = args.page == 'stub'
    args.out = args.out or ROOT / ('data/stub-runs' if stub else 'results/detections')
    if stub and (ROOT / 'results') in [args.out.resolve(), *args.out.resolve().parents]:
        ap.error('a stub run measures nothing, so it is never written into results/')
    page_url = f'{STUB_ORIGIN}/index.html' if stub else args.page
    parts = urlsplit(page_url)
    if parts.scheme not in ('http', 'https') or not parts.netloc:
        ap.error('--page must be "stub" or an http(s) URL')
    if args.tiles:
        long_side, overlap = args.tiles.split(',')
        tiling = {'kind': 'tiles', 'longSide': int(long_side), 'overlap': float(overlap)}
    else:
        tiling = {'kind': 'none'}
    transform_list = args.transforms.split(',')
    try:
        for transform in transform_list:
            transforms.parse(transform)
    except ValueError as e:
        ap.error(str(e))
    if len(set(transform_list)) < len(transform_list):
        ap.error('--transforms names a transform twice')
    nms_iou = args.nms_iou if args.nms_iou is not None else NMS_IOU[args.model]
    options = {'model': args.model, 'inputSize': args.input_size, 'tiling': tiling,
               'scoreThreshold': RUNNER_THRESHOLD, 'nmsIoU': nms_iou}

    rows = [r for r in build_manifest.read_csv(args.manifest / 'images.csv')
            if args.split == 'all' or r['split'] == args.split][:args.limit]
    files = {r['imageId']: download.image_path(args.images, r['imageId'], r['url']) for r in rows}
    bad = [r['imageId'] for r in rows
           if not files[r['imageId']].exists() or download.sha256_file(files[r['imageId']]) != r['sha256']]
    if bad:
        sys.exit(f'{len(bad)} images are missing or differ from the manifest, for example {bad[0]}; '
                 f'run eval/download.py')
    require_review(rows, args.manifest, stub)
    if 'none' in transform_list:
        check_orientations(rows, files)

    setting = 'single' if tiling['kind'] == 'none' else f'tiles{tiling["longSide"]}-{tiling["overlap"]}'
    run_id = args.run_id or (f'{datetime.date.today().isoformat()}-{"stub" if stub else "app"}-{args.model}-'
                             f'{args.input_size}-{setting}')
    if not args.run_id:
        n = 1
        while (args.out / f'{run_id}{f"-{n}" if n > 1 else ""}.jsonl').exists():
            n += 1
        run_id += f'-{n}' if n > 1 else ''
    elif (args.out / f'{run_id}.jsonl').exists():
        sys.exit(f'{args.out / run_id}.jsonl exists; every run is kept, so choose another --run-id')

    started, lines, times, served = datetime.datetime.now(datetime.timezone.utc), [], [], hashlib.sha256()
    with EvalPage(page_url, stub) as eval_page:
        for row in rows:
            path = files[row['imageId']]
            upright = None if transform_list == ['none'] else transforms.upright(path, int(row['rotation']))
            for transform in transform_list:
                name, content_type, image, expected = prepare(row, path, transform, upright)
                served.update(f'{name} {sha256(image)}\n'.encode())
                t0 = time.perf_counter()
                result = eval_page.run(DETECT, name, content_type, image, options=options)
                times.append(1000 * (time.perf_counter() - t0))
                if (result['width'], result['height']) != expected:
                    sys.exit(f'{row["imageId"]} ({transform}) decoded at {result["width"]} x {result["height"]}, '
                             f'but it should be {expected[0]} x {expected[1]}')
                lines.append({'imageId': row['imageId'], 'transform': transform, 'inputSize': args.input_size,
                              'tiling': tiling, 'boxes': result['boxes']})
    info, browser_version = eval_page.info, eval_page.version

    model_sha = sha256((STUB / 'solid-mask-stub.js').read_bytes()) if stub else info['modelSha256']
    manifest_sha = download.sha256_file(args.manifest / 'images.csv')
    run_line = {'run': run_id, 'model': args.model, 'modelSha256': model_sha, 'ortVersion': info['ortVersion'],
                'backend': info['backend'], 'threads': info['threads'], 'nmsIoU': nms_iou,
                'browser': f'Chromium {browser_version} (headless)', 'manifestSha256': manifest_sha}
    body = ''.join(json.dumps(line) + '\n' for line in lines)
    args.out.mkdir(parents=True, exist_ok=True)
    part = args.out / f'{run_id}.jsonl.part'
    part.write_text(json.dumps(run_line) + '\n' + body, encoding='utf-8')
    part.replace(args.out / f'{run_id}.jsonl')
    run_info = {
        'run': run_id, 'page': args.page, 'detectOptions': options, 'split': args.split, 'limit': args.limit,
        'transforms': transform_list, 'images': len(rows), 'boxes': sum(len(line['boxes']) for line in lines),
        'detectionsSha256': download.sha256_file(args.out / f'{run_id}.jsonl'),
        'boxesSha256': sha256(body.encode()), 'servedSha256': served.hexdigest(), 'manifestSha256': {
            name: download.sha256_file(args.manifest / name) for name in ('images.csv', 'faces.csv')},
        'pageInfo': info, 'started': started.isoformat(timespec='seconds'),
        'finished': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'),
        'msPerImage': {'median': round(statistics.median(times), 1), 'max': round(max(times), 1)} if times else None,
        'gitCommit': git_commit(), 'python': platform.python_version(), 'platform': platform.platform(),
        'playwright': metadata.version('playwright'), 'browser': browser_version,
    }
    if transform_list != ['none']:
        run_info['transformParameters'] = {**transforms.parameters(), 'pillow': metadata.version('pillow'),
                                           'numpy': metadata.version('numpy'),
                                           'littlecms': features.version('littlecms2')}
    (args.out / f'{run_id}.run_info.json').write_text(json.dumps(run_info, indent=1) + '\n', encoding='utf-8')
    print(f'{len(rows)} images x {len(transform_list)} transforms, {run_info["boxes"]} boxes: {args.out / run_id}.jsonl')


if __name__ == '__main__':
    main()
