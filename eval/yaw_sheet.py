"""Make a page on this computer for labelling the yaw of the sample faces (docs/eval-protocol.md, part B).

    python eval/yaw_sheet.py --labeller shashwat [--out data/yaw]

The sample is the first 600 faces, in the order of the SHA-256 of "solid-mask:yaw:0:<imageId>:<faceId>", among the
faces of the report split that are not depictions. The page shows one face at a time: a square crop twice the
longer side of its box, centred on it, from the upright image (transforms.upright()), with ticks at the corners of
the box and no detector output. It asks for one label per face: frontal (both eyes visible, face mostly towards the
camera), three-quarter (both eyes visible, face clearly turned), profile (one eye or none visible) or unclear.
Keys 1 to 4 choose a label; Backspace goes back one face.

The box at the bottom of the page holds the whole of eval/labels/yaw-<labeller>.csv, the labels already in that file
and the new ones; save it in place of the file, or use the download button. The page shows only faces the file does
not label yet, so labelling can stop and go on later. Each author labels alone: the page never shows the other
author's labels, and neither author opens the other's file until both are complete (yaw_agreement.py compares them).
The page loads nothing from the network and stores nothing.
"""
import argparse, html, json, re, sys
from pathlib import Path
from PIL import Image, ImageDraw
import build_manifest
import download
import transforms

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = 600
LABELS = ('frontal', 'three-quarter', 'profile', 'unclear')
LABEL_COLUMNS = ['imageId', 'faceId', 'yaw']
CROP = 256        # pixels on a side
TICK = (255, 214, 0)
PAGE = """<!doctype html>
<html lang="en">
<meta charset="utf-8">
<title>solid-mask yaw: {labeller}</title>
<style>
body {{ font: 15px system-ui, sans-serif; margin: 16px; background: #fff; color: #111; max-width: 760px }}
#crop {{ display: block; width: 384px; height: 384px; image-rendering: auto; background: #808080 }}
button {{ font: inherit; margin: 8px 8px 0 0; padding: 6px 12px }}
textarea {{ width: 100%; height: 10em; font: 12px monospace }}
</style>
<h1>Yaw labels: {labeller}</h1>
<p>Label the face between the yellow ticks. <b>Frontal</b>: both eyes visible, face mostly towards the camera.
<b>Three-quarter</b>: both eyes visible, face clearly turned. <b>Profile</b>: one eye or none visible.
<b>Unclear</b>: you can't tell. Keys 1 to 4 choose; Backspace goes back one face.</p>
<p>Label alone, and don't open the other author's file until you have both finished.</p>
<p id="progress"></p>
<img id="crop" alt="">
<div>{buttons}</div>
<h2>eval/labels/yaw-{labeller}.csv</h2>
<p>Everything in this box, the labels already in the file and the new ones, replaces the file.</p>
<textarea id="csv" readonly></textarea>
<button id="download" type="button">Download the file</button>
<script>
const faces = {faces};
const labels = new Map({existing});
const names = {names};
let at = 0;
const crop = document.getElementById('crop'), progress = document.getElementById('progress');
const csv = document.getElementById('csv');
const key = (f) => f.imageId + ',' + f.faceId;
function show() {{
  const done = faces.filter((f) => labels.has(key(f))).length;
  if (at < faces.length) {{
    crop.src = faces[at].src;
    progress.textContent = `Face ${{at + 1}} of ${{faces.length}} on this page (${{done}} labelled)`;
  }} else {{
    crop.removeAttribute('src');
    progress.textContent = `All ${{faces.length}} faces on this page are labelled. Save the box below as the file.`;
  }}
  const rows = [...labels].sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0)).map(([k, v]) => k + ',' + v);
  csv.value = ['imageId,faceId,yaw', ...rows].join('\\n') + '\\n';
}}
function choose(label) {{
  if (at >= faces.length) return;
  labels.set(key(faces[at]), label);
  at += 1;
  show();
}}
document.addEventListener('keydown', (e) => {{
  if (e.key >= '1' && e.key <= '4') choose(names[Number(e.key) - 1]);
  if (e.key === 'Backspace' && at > 0) {{ at -= 1; labels.delete(key(faces[at])); show(); e.preventDefault(); }}
}});
document.querySelectorAll('button[data-label]').forEach((b) => b.addEventListener('click', () => choose(b.dataset.label)));
document.getElementById('download').addEventListener('click', () => {{
  const link = document.createElement('a');
  link.href = URL.createObjectURL(new Blob([csv.value], {{type: 'text/csv'}}));
  link.download = 'yaw-{labeller}.csv';
  link.click();
}});
show();
</script>
</html>
"""


def sample(images, faces, n=SAMPLE):
    """The yaw sample: the first n faces, in the order of their SHA-256 key, among the report split's faces that are
    not depictions. images maps imageId to its images.csv row; faces are faces.csv rows."""
    pool = [f for f in faces if images[f['imageId']]['split'] == 'report' and f['isDepiction'] != '1']
    return sorted(pool, key=lambda f: build_manifest.digest('yaw', f'{f["imageId"]}:{f["faceId"]}'))[:n]


def read_labels(path):
    """{(imageId, faceId): label} from a labels file, after checking every row."""
    labels = {}
    rows = build_manifest.read_csv(path) if path.exists() else []
    if rows and list(rows[0]) != LABEL_COLUMNS:
        sys.exit(f'{path}: the columns must be {",".join(LABEL_COLUMNS)}')
    for line, row in enumerate(rows, start=2):
        face = (row['imageId'], row['faceId'])
        if row['yaw'] not in LABELS or face in labels:
            sys.exit(f'{path}, line {line}: expected a face not labelled before and one of {", ".join(LABELS)}')
        labels[face] = row['yaw']
    return labels


def crop(image, face, size=CROP):
    """A size x size crop centred on the face's box, twice its longer side, with mid-grey beyond the edges of the
    image and yellow ticks just outside the corners of the box."""
    x, y, w, h = (float(face[k]) for k in 'xywh')
    side = 2 * max(w, h)
    left, top = x + w / 2 - side / 2, y + h / 2 - side / 2
    scale = size / side
    x0, y0 = max(0.0, left), max(0.0, top)
    x1, y1 = min(float(image.width), left + side), min(float(image.height), top + side)
    canvas = Image.new('RGB', (size, size), transforms.FILL)
    part = image.resize((max(1, round((x1 - x0) * scale)), max(1, round((y1 - y0) * scale))),
                        Image.Resampling.LANCZOS, box=(x0, y0, x1, y1))
    canvas.paste(part, (round((x0 - left) * scale), round((y0 - top) * scale)))
    pen = ImageDraw.Draw(canvas)
    bx0, by0 = (x - left) * scale - 3, (y - top) * scale - 3
    bx1, by1 = (x + w - left) * scale + 3, (y + h - top) * scale + 3
    arm = 12
    for cx, cy, dx, dy in ((bx0, by0, 1, 1), (bx1, by0, -1, 1), (bx0, by1, 1, -1), (bx1, by1, -1, -1)):
        pen.line([(cx, cy + dy * arm), (cx, cy), (cx + dx * arm, cy)], fill=TICK, width=2)
    return canvas


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--labeller', required=True, help='a short name in lower case, such as shashwat')
    ap.add_argument('--manifest', type=Path, default=ROOT / 'eval/manifest')
    ap.add_argument('--labels', type=Path, default=ROOT / 'eval/labels')
    ap.add_argument('--images', type=Path, default=ROOT / 'data/openimages/images')
    ap.add_argument('--out', type=Path, default=ROOT / 'data/yaw')
    args = ap.parse_args(argv)
    if not re.fullmatch(r'[a-z0-9-]+', args.labeller):
        ap.error('--labeller must be lower-case letters, digits and hyphens')

    images = {r['imageId']: r for r in build_manifest.read_csv(args.manifest / 'images.csv')}
    chosen = sample(images, build_manifest.read_csv(args.manifest / 'faces.csv'))
    existing = read_labels(args.labels / f'yaw-{args.labeller}.csv')
    todo = [f for f in chosen if (f['imageId'], f['faceId']) not in existing]
    out = args.out / args.labeller
    out.mkdir(parents=True, exist_ok=True)
    for i in dict.fromkeys(f['imageId'] for f in todo):
        image = transforms.upright(download.image_path(args.images, i, images[i]['url']), int(images[i]['rotation']))
        for face in (f for f in todo if f['imageId'] == i):
            crop(image, face).save(out / f'{i}_{face["faceId"]}.jpg', quality=92)
    page_faces = [{'imageId': f['imageId'], 'faceId': f['faceId'], 'src': f'{f["imageId"]}_{f["faceId"]}.jpg'}
                  for f in todo]
    buttons = ''.join(f'<button type="button" data-label="{label}">{n} {label}</button>'
                      for n, label in enumerate(LABELS, start=1))
    existing_pairs = [[f'{i},{n}', label] for (i, n), label in sorted(existing.items())]
    (out / 'index.html').write_text(PAGE.format(
        labeller=html.escape(args.labeller), buttons=buttons, faces=json.dumps(page_faces),
        existing=json.dumps(existing_pairs), names=json.dumps(LABELS)), encoding='utf-8')
    outside = len(set(existing) - {(f['imageId'], f['faceId']) for f in chosen})
    print(f'{len(chosen)} faces in the sample; {len(chosen) - len(todo)} labelled by {args.labeller}, {len(todo)} to go'
          + (f'; {outside} labelled faces are no longer in the sample' if outside else '')
          + f'. Open {out / "index.html"} in a browser.')


if __name__ == '__main__':
    main()
