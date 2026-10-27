"""Make a page on this computer for the review and the rotation check: upright images with their face boxes.

    python eval/review_sheet.py [--unreviewed | --rotated | --all | IMAGE_ID ...] [--limit N] [--out data/review]

For each chosen image of eval/manifest/images.csv, writes <out>/<imageId>.jpg: the image turned upright by its
Rotation, with every face box of eval/manifest/faces.csv outlined and numbered by faceId, green for faces and
orange for depictions. <out>/index.html shows these images with a choice for each one that has no row in
eval/manifest/review.csv yet: keep, or remove with a reason code (docs/eval-protocol.md, part B, "Review"). The
box at the bottom of the page collects the matching rows, to be pasted into review.csv. The page loads nothing
from the network and stores nothing, so reloading it clears the choices. Without arguments it shows the images
not yet reviewed.
"""
import argparse, html
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import build_manifest
import download

ROOT = Path(__file__).resolve().parents[1]
FACE, DEPICTION = (0, 255, 0), (255, 140, 0)
PAGE = """<!doctype html>
<html lang="en">
<meta charset="utf-8">
<title>solid-mask review</title>
<style>
body {{ font: 14px system-ui, sans-serif; margin: 16px; background: #fff; color: #111 }}
figure {{ display: inline-block; vertical-align: top; margin: 0 16px 24px 0 }}
img {{ display: block; max-width: 512px; max-height: 512px }}
textarea {{ width: 100%; height: 12em; font: 12px monospace }}
</style>
<h1>{count} images</h1>
<p>Green boxes are faces and orange boxes are depictions. Remove an image if it is intimate or sexual
(<code>intimate</code>), if there is any doubt about that (<code>doubtful</code>), or if a visible face has no box
(<code>unboxed-face</code>); otherwise keep it. Reviewer: <input id="reviewer" size="24"></p>
{figures}
<h2>Rows for eval/manifest/review.csv</h2>
<textarea id="rows" readonly></textarea>
<script>
const rows = document.getElementById("rows"), reviewer = document.getElementById("reviewer");
const cell = v => /[",\\n]/.test(v) ? '"' + v.replaceAll('"', '""') + '"' : v;
function update() {{
  if (!reviewer.value.trim()) {{ rows.value = "Type your name as reviewer first."; return; }}
  rows.value = [...document.querySelectorAll("select")].filter(s => s.value).map(s => {{
    const [decision, reason = ""] = s.value.split(":");
    return [s.dataset.id, decision, reason, reviewer.value.trim()].map(cell).join(",");
  }}).join("\\n");
}}
document.addEventListener("change", update);
reviewer.addEventListener("input", update);
</script>
</html>
"""


def draw(src, dest, rotation, faces):
    """Save the image at src turned counterclockwise by rotation, with the faces' upright boxes drawn on it."""
    with Image.open(src) as im:
        im = im.convert('RGB').rotate(rotation, expand=True)
    line = max(2, round(max(im.size) / 300))
    font = ImageFont.load_default(size=6 * line)
    pen = ImageDraw.Draw(im)
    for face in faces:
        x, y, w, h = (float(face[k]) for k in 'xywh')
        colour = DEPICTION if face['isDepiction'] == '1' else FACE
        pen.rectangle([x, y, x + w, y + h], outline=colour, width=line)
        pen.text((x + 2 * line, y + line), face['faceId'], fill=colour, font=font)
    im.save(dest, quality=90)


def figure(image, n_faces, decision):
    i = html.escape(image['imageId'])
    turned = f'turned {image["rotation"]}°' if image['rotation'] != '0' else 'upright'
    if decision:
        choice = f'reviewed: {decision}'
    else:
        options = ['<option value="">not reviewed</option>', '<option value="keep">keep</option>']
        options += [f'<option value="remove:{r}">remove: {r}</option>' for r in build_manifest.REASONS]
        choice = f'<select data-id="{i}">{"".join(options)}</select>'
    return (f'<figure><img src="{i}.jpg" alt="" loading="lazy"><figcaption>{i} · {image["split"]} · {turned} · '
            f'{n_faces} face{"s" * (n_faces != 1)}<br>{choice}</figcaption></figure>')


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    which = ap.add_mutually_exclusive_group()
    which.add_argument('--unreviewed', action='store_true', help='images with no row in review.csv (default)')
    which.add_argument('--rotated', action='store_true', help='images stored turned, for the rotation check')
    which.add_argument('--all', action='store_true')
    which.add_argument('ids', nargs='*', default=[], metavar='IMAGE_ID')
    ap.add_argument('--limit', type=int, help='show at most this many images')
    ap.add_argument('--manifest', type=Path, default=ROOT / 'eval/manifest')
    ap.add_argument('--images', type=Path, default=ROOT / 'data/openimages/images')
    ap.add_argument('--out', type=Path, default=ROOT / 'data/review')
    args = ap.parse_args(argv)

    images = build_manifest.read_csv(args.manifest / 'images.csv')
    faces = {}
    for face in build_manifest.read_csv(args.manifest / 'faces.csv'):
        faces.setdefault(face['imageId'], []).append(face)
    review = build_manifest.read_review(args.manifest / 'review.csv')
    if args.ids:
        known = {r['imageId'] for r in images}
        if unknown := [i for i in args.ids if i not in known]:
            ap.error(f'not in {args.manifest / "images.csv"}: {", ".join(unknown)}')
        wanted = set(args.ids)
        chosen = [r for r in images if r['imageId'] in wanted]
    elif args.rotated:
        chosen = [r for r in images if r['rotation'] != '0']
    elif args.all:
        chosen = images
    else:
        chosen = [r for r in images if r['imageId'] not in review]
    chosen = chosen[:args.limit]

    args.out.mkdir(parents=True, exist_ok=True)
    for image in chosen:
        i = image['imageId']
        draw(download.image_path(args.images, i, image['url']), args.out / f'{i}.jpg', int(image['rotation']),
             faces.get(i, []))
    figures = '\n'.join(figure(r, len(faces.get(r['imageId'], [])), review.get(r['imageId'])) for r in chosen)
    (args.out / 'index.html').write_text(PAGE.format(count=len(chosen), figures=figures), encoding='utf-8')
    print(f'{len(chosen)} images: open {args.out / "index.html"} in a browser')


if __name__ == '__main__':
    main()
