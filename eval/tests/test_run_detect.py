"""Tests of run_detect.py: the runner drives the stub page in headless Chromium on made-up photos whose faces are
magenta rectangles, and score.py scores the result."""
import hashlib, io, json
import pytest
from PIL import Image, ImageOps
import build_manifest as bm
import run_detect
import score

UPRIGHT = (240, 320)                             # width, height of the made-up photo, upright
FACES = [(40, 50, 60, 80), (150, 200, 50, 40)]   # x, y, w, h


def stored_jpeg(rotation):
    """The made-up photo as Open Images would store it: turned clockwise, so that turning it counterclockwise by
    rotation makes it upright."""
    photo = Image.new('RGB', UPRIGHT, (90, 110, 130))
    for x, y, w, h in FACES:
        photo.paste((255, 0, 255), (x, y, x + w, y + h))
    buffer = io.BytesIO()
    photo.rotate(-rotation, expand=True).save(buffer, 'JPEG', quality=100, subsampling=0)
    return buffer.getvalue()


def tagged_jpeg(rotation, orientation):
    """stored_jpeg() carrying an EXIF orientation tag of its own."""
    exif = Image.Exif()
    exif[0x0112] = orientation
    buffer = io.BytesIO()
    Image.open(io.BytesIO(stored_jpeg(rotation))).save(buffer, 'JPEG', quality=100, subsampling=0,
                                                       exif=exif.tobytes())
    return buffer.getvalue()


def replace_image(folder, image_id, jpeg):
    """Put another file in place of an image of the made-up test set, with its SHA-256 in the manifest."""
    (folder / 'images' / f'{image_id}.jpg').write_bytes(jpeg)
    rows = bm.read_csv(folder / 'manifest/images.csv')
    for r in rows:
        if r['imageId'] == image_id:
            r['sha256'] = hashlib.sha256(jpeg).hexdigest()
    bm.write_csv(folder / 'manifest/images.csv', bm.IMAGE_COLUMNS, rows)


def make_test_set(folder):
    (folder / 'images').mkdir(parents=True)
    (folder / 'manifest').mkdir()
    images, faces = [], []
    for rotation in (0, 90, 180, 270):
        i, jpeg = f'r{rotation:03d}', stored_jpeg(rotation)
        (folder / 'images' / f'{i}.jpg').write_bytes(jpeg)
        images.append({'imageId': i, 'split': 'report', 'url': f'https://example.org/{i}.jpg',
                       'sha256': hashlib.sha256(jpeg).hexdigest(), 'width': UPRIGHT[0], 'height': UPRIGHT[1],
                       'rotation': rotation})
        faces += [{'imageId': i, 'faceId': n, 'x': x, 'y': y, 'w': w, 'h': h, 'isOccluded': 0, 'isTruncated': 0,
                   'isDepiction': 0, 'yaw': ''} for n, (x, y, w, h) in enumerate(FACES)]
    bm.write_csv(folder / 'manifest/images.csv', bm.IMAGE_COLUMNS, images)
    bm.write_csv(folder / 'manifest/faces.csv', bm.FACE_COLUMNS, faces)
    return ['--manifest', str(folder / 'manifest'), '--images', str(folder / 'images'), '--out', str(folder / 'out')]


def keep_all(folder):
    """Record a "keep" for every image of the made-up test set, as the review would."""
    bm.write_csv(folder / 'manifest/review.csv', bm.REVIEW_COLUMNS,
                 [{'imageId': r['imageId'], 'decision': 'keep', 'reason': '', 'reviewer': 'test'}
                  for r in bm.read_csv(folder / 'manifest/images.csv')])


def test_with_orientation_adds_the_tag_pillow_reads():
    for rotation in (90, 180, 270):
        tagged = run_detect.with_orientation(stored_jpeg(rotation), rotation)
        assert tagged[2:4] == b'\xff\xe0'  # the JFIF segment stays first
        image = Image.open(io.BytesIO(tagged))
        assert image.getexif()[0x0112] == run_detect.EXIF_ORIENTATION[rotation]
        assert ImageOps.exif_transpose(image).size == UPRIGHT
        with pytest.raises(ValueError, match='already has EXIF'):
            run_detect.with_orientation(tagged, rotation)
    assert run_detect.with_orientation(stored_jpeg(0), 0) == stored_jpeg(0)
    padded = stored_jpeg(90)
    padded = padded[:2] + b'\xff\xff' + padded[2:]  # fill bytes before the first segment are allowed
    assert Image.open(io.BytesIO(run_detect.with_orientation(padded, 90))).getexif()[0x0112] == 8


def test_runner_turns_every_image_upright_and_reruns_identically(chromium, tmp_path):
    args = make_test_set(tmp_path)
    run_detect.main(args + ['--run-id', 'a'])
    lines = [json.loads(line) for line in (tmp_path / 'out/a.jsonl').read_text().splitlines()]
    assert list(lines[0]) == ['run', 'model', 'modelSha256', 'ortVersion', 'backend', 'threads', 'nmsIoU',
                              'browser', 'manifestSha256']
    assert lines[0]['run'] == 'a' and lines[0]['backend'] == 'stub' and lines[0]['nmsIoU'] == 0.3
    assert [line['imageId'] for line in lines[1:]] == ['r000', 'r090', 'r180', 'r270']
    for line in lines[1:]:
        assert line['transform'] == 'none' and line['inputSize'] == 640 and line['tiling'] == {'kind': 'none'}
        boxes = sorted(tuple(b[:4]) for b in line['boxes'])
        assert len(boxes) == len(FACES) and all(b[4] == 0.9 for b in line['boxes'])
        for got, want in zip(boxes, sorted(FACES)):
            assert max(abs(g - w) for g, w in zip(got, want)) <= 1, (line['imageId'], got, want)

    score.main([str(tmp_path / 'out/a.jsonl'), '--pad', '0', '--threshold', '0.5', '--split', 'all',
                '--manifest', str(tmp_path / 'manifest'), '--out', str(tmp_path / 'score.json')])
    group = json.loads((tmp_path / 'score.json').read_text())['groups'][0]
    assert group['images'] == 4 and group['faces'] == 8 and group['missRate']['value'] == 0
    assert group['recallIoU50']['value'] == 1 and group['falseMasksPerImage']['value'] == 0

    run_detect.main(args + ['--run-id', 'b'])
    a, b = ((tmp_path / f'out/{r}.jsonl').read_text().splitlines() for r in 'ab')
    assert a[1:] == b[1:]
    info = {r: json.loads((tmp_path / f'out/{r}.run_info.json').read_text()) for r in 'ab'}
    assert info['a']['boxesSha256'] == info['b']['boxesSha256'] and info['a']['images'] == 4
    with pytest.raises(SystemExit, match='every run is kept'):
        run_detect.main(args + ['--run-id', 'a'])
    run_detect.main(args + ['--split', 'report', '--limit', '1'])  # a run id of its own, never an old one
    assert len(list((tmp_path / 'out').glob('*-stub-yunet-640-single.jsonl'))) == 1


def test_runner_makes_each_transform_and_score_reads_it(chromium, tmp_path):
    """Rotated copies keep every face covered. At 45 degrees the usual recall drops while every face stays covered:
    the exact box around a face turned 45 degrees has IoU 0.49 with it, and the stub's box, a little smaller at the
    corners, sometimes just passes 0.5. Darkened by 2 EV, the stub's magenta is too dark for it to find."""
    args = make_test_set(tmp_path) + ['--run-id', 't', '--transforms', 'none,rot0,rot45,rot90,dark2']
    run_detect.main(args)
    lines = [json.loads(line) for line in (tmp_path / 'out/t.jsonl').read_text().splitlines()][1:]
    assert [(line['imageId'], line['transform']) for line in lines] == [
        (i, t) for i in ('r000', 'r090', 'r180', 'r270') for t in ('none', 'rot0', 'rot45', 'rot90', 'dark2')]
    info = json.loads((tmp_path / 'out/t.run_info.json').read_text())
    assert info['transforms'] == ['none', 'rot0', 'rot45', 'rot90', 'dark2']
    assert info['transformParameters']['darkening']['lambdaShot'] == pytest.approx(0.0010954, rel=1e-4)
    run_detect.main(args[:6] + ['--run-id', 'u', '--transforms', 'none,rot0,rot45,rot90,dark2'])  # a rerun
    again = json.loads((tmp_path / 'out/u.run_info.json').read_text())
    assert again['servedSha256'] == info['servedSha256'] and again['boxesSha256'] == info['boxesSha256']

    score.main([str(tmp_path / 'out/t.jsonl'), '--pad', '0', '--threshold', '0.5', '--split', 'all',
                '--manifest', str(tmp_path / 'manifest'), '--out', str(tmp_path / 'score.json')])
    groups = {g['transform']: g for g in json.loads((tmp_path / 'score.json').read_text())['groups']}
    for t in ('none', 'rot0', 'rot45', 'rot90'):
        assert groups[t]['faces'] == 8 and groups[t]['missRate']['value'] == 0, t
        assert groups[t]['falseMasksPerImage']['value'] == 0, t
    assert groups['rot0']['recallIoU50']['value'] == groups['rot90']['recallIoU50']['value'] == 1
    assert groups['rot45']['recallIoU50']['value'] < 1
    assert groups['dark2']['missRate']['value'] == 1

    for bad in ('blur3', 'none,none'):
        with pytest.raises(SystemExit):
            run_detect.main(args[:-1] + [bad])


def test_runner_refuses_images_that_differ_from_the_manifest(tmp_path):
    args = make_test_set(tmp_path)
    (tmp_path / 'images/r090.jpg').write_bytes(b'not the image')
    with pytest.raises(SystemExit, match='run eval/download.py'):
        run_detect.main(args)


def test_runner_checks_before_starting_the_browser(tmp_path, monkeypatch):
    args = make_test_set(tmp_path)
    with pytest.raises(SystemExit):  # a stub run never goes into results/
        run_detect.main(args[:-2] + ['--out', str(run_detect.ROOT / 'results/detections')])
    for i, jpeg, refusal in (('r000', tagged_jpeg(0, 3), 'carries EXIF orientation 3'),
                             ('r090', run_detect.with_orientation(stored_jpeg(90), 90), 'carries EXIF orientation 8'),
                             ('r090', tagged_jpeg(90, 1), 'already has EXIF')):
        folder = tmp_path / f'{i}-{refusal.split()[-1]}'
        args = make_test_set(folder)
        replace_image(folder, i, jpeg)
        for transform in ('none', 'rot0'):  # a file's own tag counts whatever the transform
            if refusal != 'already has EXIF' or transform == 'none':
                with pytest.raises(SystemExit, match=refusal):
                    run_detect.main(args + ['--transforms', transform])
    rows = bm.read_csv(folder / 'manifest/images.csv')  # served as upright PNGs, the images need no tag
    run_detect.check_orientations(rows, {r['imageId']: folder / 'images' / f'{r["imageId"]}.jpg' for r in rows},
                                  as_stored=False)


def test_runner_stops_when_the_page_asks_another_origin(chromium, site, tmp_path):
    base, folder, requested = site
    args = make_test_set(tmp_path)
    (folder / 'solid-mask-stub.js').write_bytes((run_detect.STUB / 'solid-mask-stub.js').read_bytes())
    (folder / 'index.html').write_text('<!doctype html><script type="module" src="solid-mask-stub.js"></script>'
                                       '<script>fetch("https://example.org/beacon").catch(() => {})</script>')
    with pytest.raises(SystemExit, match='before it is reviewed'):  # a real page runs only on reviewed images
        run_detect.main(args + ['--page', f'{base}/index.html'])
    keep_all(tmp_path)
    with pytest.raises(SystemExit, match='another origin'):
        run_detect.main(args + ['--page', f'{base}/index.html'])
    assert '/index.html' in requested and not any(p.startswith(run_detect.IMAGE_PATH) for p in requested)
    assert not list((tmp_path / 'out').glob('*.jsonl'))
