"""Check that transforms.upright() gives the pixels Chromium decodes, for test images with each kind of ICC profile.

    python eval/check_colour.py [--per-kind 6]

run_detect.py lets the page decode an untransformed image itself, but makes the rotated and darkened copies from
transforms.upright(), which converts the image to sRGB with LittleCMS. This script decodes up to --per-kind test
images of each kind (no profile, or the profile's description, the image's mode and the profile's colour space) in
headless Chromium, the way the page does (createImageBitmap with imageOrientation "from-image", then a canvas), and
compares the pixels with transforms.upright(). It prints the largest difference for each kind, and stops with an
error if any is more than 1 or a size differs. Rerun it after updating Chromium, Pillow or LittleCMS.
"""
import argparse, base64, io, sys
from pathlib import Path
import numpy as np
from PIL import Image, ImageCms
import build_manifest
import download
import run_detect
import transforms

ROOT = Path(__file__).resolve().parents[1]
DECODE = """async (url) => {
  const bitmap = await createImageBitmap(await (await fetch(url)).blob(), {imageOrientation: 'from-image'});
  const context = new OffscreenCanvas(bitmap.width, bitmap.height).getContext('2d');
  context.drawImage(bitmap, 0, 0);
  const rgba = context.getImageData(0, 0, bitmap.width, bitmap.height).data;
  let text = '';
  for (let i = 0; i < rgba.length; i += 32768) text += String.fromCharCode(...rgba.subarray(i, i + 32768));
  return {width: bitmap.width, height: bitmap.height, rgba: btoa(text)};
}"""


def kind(path):
    with Image.open(path) as image:
        icc = image.info.get('icc_profile')
        if not icc:
            return f'no profile ({image.mode})'
        profile = ImageCms.ImageCmsProfile(io.BytesIO(icc))
        try:
            name = ImageCms.getProfileDescription(profile).strip()
        except ImageCms.PyCMSError:
            name = '(unreadable description)'
        return f'{name} ({image.mode}, profile {profile.profile.xcolor_space.strip()})'


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--per-kind', type=int, default=6, help='images compared per kind of profile')
    ap.add_argument('--manifest', type=Path, default=ROOT / 'eval/manifest')
    ap.add_argument('--images', type=Path, default=ROOT / 'data/openimages/images')
    args = ap.parse_args(argv)

    rows = {r['imageId']: r for r in build_manifest.read_csv(args.manifest / 'images.csv')}
    files = {i: download.image_path(args.images, i, r['url']) for i, r in rows.items()}
    kinds = {}
    for i in sorted(rows):
        kinds.setdefault(kind(files[i]), []).append(i)
    chosen = [(k, i) for k, ids in sorted(kinds.items()) for i in ids[:args.per_kind]]

    def route(request_route):
        name = request_route.request.url.rsplit('/', 1)[-1]
        if name == 'index.html':
            return request_route.fulfill(status=200, content_type='text/html', body='<!doctype html><title>check</title>')
        i = name.rsplit('.', 1)[0]
        body = run_detect.with_orientation(files[i].read_bytes(), int(rows[i]['rotation']))
        return request_route.fulfill(status=200, content_type='image/jpeg', body=body)

    from playwright.sync_api import sync_playwright
    worst, problems = {}, []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page()
            page.route(f'{run_detect.STUB_ORIGIN}/**', route)
            page.goto(f'{run_detect.STUB_ORIGIN}/index.html')
            for k, i in chosen:
                out = page.evaluate(DECODE, f'{run_detect.STUB_ORIGIN}/{i}.jpg')
                chromium = np.frombuffer(base64.b64decode(out['rgba']), np.uint8).reshape(out['height'], out['width'], 4)
                ours = np.asarray(transforms.upright(files[i], int(rows[i]['rotation'])))
                if chromium.shape[:2] != ours.shape[:2]:
                    problems.append(f'{i}: Chromium {chromium.shape[1]} x {chromium.shape[0]}, '
                                    f'upright() {ours.shape[1]} x {ours.shape[0]}')
                    continue
                difference = int(np.abs(chromium[:, :, :3].astype(int) - ours.astype(int)).max())
                worst[k] = max(worst.get(k, 0), difference)
                if difference > 1:
                    problems.append(f'{i} ({k}): differs from Chromium by up to {difference}')
            version = browser.version
        finally:
            browser.close()
    print(f'Chromium {version}; {len(chosen)} images of {len(kinds)} kinds; largest difference per kind:')
    for k in sorted(worst, key=lambda k: (-worst[k], k)):
        print(f'  {worst[k]}  {k} ({min(len(kinds[k]), args.per_kind)} of {len(kinds[k])} images)')
    if problems:
        sys.exit('\n'.join(problems))


if __name__ == '__main__':
    main()
