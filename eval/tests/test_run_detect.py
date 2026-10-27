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


@pytest.fixture(scope='module')
def chromium():
    playwright = pytest.importorskip('playwright.sync_api')
    try:
        with playwright.sync_playwright() as pw:
            pw.chromium.launch().close()
    except playwright.Error as e:
        pytest.skip(f'no Chromium for Playwright (python -m playwright install --only-shell chromium): {e}')


def stored_jpeg(rotation):
    """The made-up photo as Open Images would store it: turned clockwise, so that turning it counterclockwise by
    rotation makes it upright."""
    photo = Image.new('RGB', UPRIGHT, (90, 110, 130))
    for x, y, w, h in FACES:
        photo.paste((255, 0, 255), (x, y, x + w, y + h))
    buffer = io.BytesIO()
    photo.rotate(-rotation, expand=True).save(buffer, 'JPEG', quality=100, subsampling=0)
    return buffer.getvalue()


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


def test_runner_refuses_images_that_differ_from_the_manifest(tmp_path):
    args = make_test_set(tmp_path)
    (tmp_path / 'images/r090.jpg').write_bytes(b'not the image')
    with pytest.raises(SystemExit, match='run eval/download.py'):
        run_detect.main(args)


def test_runner_stops_when_the_page_asks_another_origin(chromium, site, tmp_path):
    base, folder, requested = site
    args = make_test_set(tmp_path)
    (folder / 'solid-mask-stub.js').write_bytes((run_detect.STUB / 'solid-mask-stub.js').read_bytes())
    (folder / 'index.html').write_text('<!doctype html><script type="module" src="solid-mask-stub.js"></script>'
                                       '<script>fetch("https://example.org/beacon").catch(() => {})</script>')
    with pytest.raises(SystemExit, match='another origin'):
        run_detect.main(args + ['--page', f'{base}/index.html'])
    assert '/index.html' in requested and not any(p.startswith(run_detect.IMAGE_PATH) for p in requested)
    assert not list((tmp_path / 'out').glob('*.jsonl'))
