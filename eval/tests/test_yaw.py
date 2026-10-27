"""Tests of yaw_sheet.py and yaw_agreement.py on made-up faces and labels."""
import json
import numpy as np
import pytest
from PIL import Image
import build_manifest as bm
import yaw_agreement
import yaw_sheet

LABELLERS = ['ann', 'bob']


def make_manifest(folder, n_images=30, faces_per_image=3):
    """Made-up images (grey, with a white square per face) and faces; every third face is a depiction."""
    (folder / 'manifest').mkdir()
    (folder / 'images').mkdir()
    images, faces = [], []
    for k in range(n_images):
        i = f'{k:016x}'
        images.append({'imageId': i, 'split': bm.split_of(i), 'url': f'https://example.org/{i}.jpg', 'width': 120,
                       'height': 90, 'rotation': 0})
        image = Image.new('RGB', (120, 90), (90, 90, 90))
        for n in range(faces_per_image):
            image.paste((255, 255, 255), (10 + 35 * n, 30, 30 + 35 * n, 55))
            faces.append({'imageId': i, 'faceId': n, 'x': 10 + 35 * n, 'y': 30, 'w': 20, 'h': 25,
                          'isOccluded': 0, 'isTruncated': 0, 'isDepiction': int(n == 2), 'yaw': ''})
        image.save(folder / 'images' / f'{i}.jpg', quality=95)
    bm.write_csv(folder / 'manifest/images.csv', bm.IMAGE_COLUMNS, images)
    bm.write_csv(folder / 'manifest/faces.csv', bm.FACE_COLUMNS, faces)
    return ['--manifest', str(folder / 'manifest'), '--labels', str(folder / 'labels')]


def manifest_rows(folder):
    return ({r['imageId']: r for r in bm.read_csv(folder / 'manifest/images.csv')},
            bm.read_csv(folder / 'manifest/faces.csv'))


def write_labels(folder, name, labels):
    (folder / 'labels').mkdir(exist_ok=True)
    bm.write_csv(folder / 'labels' / f'yaw-{name}.csv', yaw_sheet.LABEL_COLUMNS,
                 [{'imageId': i, 'faceId': n, 'yaw': label} for (i, n), label in sorted(labels.items())])


def test_sample_takes_report_faces_that_are_not_depictions_in_a_fixed_order(tmp_path):
    make_manifest(tmp_path)
    images, faces = manifest_rows(tmp_path)
    chosen = yaw_sheet.sample(images, faces, n=10)
    assert len(chosen) == 10 and chosen == yaw_sheet.sample(images, faces, n=10)
    assert all(images[f['imageId']]['split'] == 'report' and f['isDepiction'] == '0' for f in chosen)
    gone = chosen[0]['imageId']  # removing an image keeps every other face's place in the order
    rest = yaw_sheet.sample({i: r for i, r in images.items() if i != gone}, [f for f in faces if f['imageId'] != gone], n=10)
    kept = [f for f in chosen if f['imageId'] != gone]
    assert rest[:len(kept)] == kept


def test_crop_centres_the_face_and_pads_beyond_the_image():
    image = Image.new('RGB', (100, 80), (0, 0, 0))
    image.paste((255, 255, 255), (0, 0, 20, 20))          # a face in the top-left corner
    out = yaw_sheet.crop(image, {'x': 0, 'y': 0, 'w': 20, 'h': 20})
    pixels = np.asarray(out).astype(int)
    assert out.size == (yaw_sheet.CROP, yaw_sheet.CROP)
    assert (pixels[5, 5] == yaw_sheet.transforms.FILL).all()                  # beyond the image: mid-grey
    assert (pixels[128, 128] > 240).all()                                     # the face is in the middle
    assert (np.abs(pixels[61, 61:70] - yaw_sheet.TICK).max(axis=1) < 40).any()  # a tick at the top-left corner


def test_sheet_shows_only_faces_not_yet_labelled(tmp_path):
    args = make_manifest(tmp_path) + ['--images', str(tmp_path / 'images'), '--out', str(tmp_path / 'yaw')]
    images, faces = manifest_rows(tmp_path)
    chosen = yaw_sheet.sample(images, faces)
    done = {(f['imageId'], f['faceId']): 'frontal' for f in chosen[:5]}
    write_labels(tmp_path, 'ann', done)
    yaw_sheet.main(args + ['--labeller', 'ann'])
    page = (tmp_path / 'yaw/ann/index.html').read_text(encoding='utf-8')
    shown = json.loads(page.split('const faces = ', 1)[1].split(';\n', 1)[0])
    assert len(shown) == len(chosen) - 5 and not {(f['imageId'], f['faceId']) for f in shown} & set(done)
    assert all((tmp_path / 'yaw/ann' / f['src']).exists() for f in shown)
    assert 'bob' not in page
    with pytest.raises(SystemExit):
        yaw_sheet.main(args + ['--labeller', 'Ann Smith'])
    write_labels(tmp_path, 'ann', {**done, ('x', '0'): 'sideways'})
    with pytest.raises(SystemExit):
        yaw_sheet.main(args + ['--labeller', 'ann'])


def test_kappa_matches_a_worked_example():
    # 50 faces: both frontal 20, first frontal and second profile 5, the reverse 10, both profile 15. Agreement 0.7,
    # chance agreement 0.5, so kappa = 0.4.
    table = np.zeros((4, 4))
    table[0, 0], table[0, 2], table[2, 0], table[2, 2] = 20, 5, 10, 15
    assert yaw_agreement.kappa(table) == pytest.approx(0.4)
    assert yaw_agreement.kappa(np.diag([3, 0, 2, 0])) == 1
    assert yaw_agreement.kappa(np.zeros((4, 4))) is None and yaw_agreement.kappa(np.diag([5, 0, 0, 0])) is None


def test_agreement_reports_kappa_and_keeps_settled_labels(tmp_path, capsys):
    args = make_manifest(tmp_path) + ['--labellers', *LABELLERS]
    images, faces = manifest_rows(tmp_path)
    chosen = [(f['imageId'], f['faceId']) for f in yaw_sheet.sample(images, faces)]
    rng = np.random.default_rng(0)
    ann = {face: yaw_sheet.LABELS[k] for face, k in zip(chosen, rng.integers(0, 3, len(chosen)))}
    bob = dict(ann)
    for face in chosen[:6]:
        bob[face] = 'unclear'
    write_labels(tmp_path, 'ann', ann)
    write_labels(tmp_path, 'bob', {face: label for face, label in bob.items() if face != chosen[-1]})
    with pytest.raises(SystemExit, match='1 faces of the sample unlabelled'):
        yaw_agreement.main(args)
    write_labels(tmp_path, 'bob', {**bob, ('removed-in-review', '0'): 'frontal'})

    yaw_agreement.main(args + ['--out', str(tmp_path / 'agreement.json')])
    summary = json.loads((tmp_path / 'agreement.json').read_text())
    assert summary['labelsOutsideSample'] == {'ann': 0, 'bob': 1}
    assert summary['faces'] == len(chosen) and summary['disagreements'] == 6 == summary['unsettled']
    assert summary['observedAgreement'] == pytest.approx(1 - 6 / len(chosen))
    assert 0 < summary['kappa']['low'] <= summary['kappa']['value'] <= summary['kappa']['high'] <= 1
    assert summary['kappaWithoutUnclear']['value'] == 1 and summary['kappaWithoutUnclear']['faces'] == len(chosen) - 6
    assert summary['counts']['bob']['unclear'] == 6 + list(ann.values()).count('unclear')
    with pytest.raises(SystemExit, match='not settled'):
        yaw_agreement.main(args + ['--write'])

    disagreements = bm.read_csv(tmp_path / 'labels/yaw-disagreements.csv')
    for row in disagreements:
        row['settled'] = row['first']
    bm.write_csv(tmp_path / 'labels/yaw-disagreements.csv', yaw_agreement.DISAGREEMENT_COLUMNS, disagreements)
    yaw_agreement.main(args)  # a rerun keeps what was settled
    assert all(r['settled'] for r in bm.read_csv(tmp_path / 'labels/yaw-disagreements.csv'))
    yaw_agreement.main(args + ['--write'])
    written = {(f['imageId'], f['faceId']): f['yaw'] for f in bm.read_csv(tmp_path / 'manifest/faces.csv')}
    assert {face: written[face] for face in chosen} == ann
    assert sum(1 for label in written.values() if label) == len(chosen)
    capsys.readouterr()


def test_sheet_page_records_keys_and_backspace(chromium, tmp_path):
    from playwright.sync_api import sync_playwright
    args = make_manifest(tmp_path) + ['--images', str(tmp_path / 'images'), '--out', str(tmp_path / 'yaw')]
    images, faces = manifest_rows(tmp_path)
    chosen = yaw_sheet.sample(images, faces)
    write_labels(tmp_path, 'ann', {(chosen[0]['imageId'], chosen[0]['faceId']): 'profile'})
    yaw_sheet.main(args + ['--labeller', 'ann'])
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.goto((tmp_path / 'yaw/ann/index.html').as_uri())
        for key in ('1', '3', 'Backspace', '2', '4'):
            page.keyboard.press(key)
        text = page.locator('#csv').input_value()
        progress = page.locator('#progress').inner_text()
        browser.close()
    rows = text.strip().split('\n')
    expected = {f'{chosen[0]["imageId"]},{chosen[0]["faceId"]},profile',
                f'{chosen[1]["imageId"]},{chosen[1]["faceId"]},frontal',
                f'{chosen[2]["imageId"]},{chosen[2]["faceId"]},three-quarter',
                f'{chosen[3]["imageId"]},{chosen[3]["faceId"]},unclear'}
    assert rows[0] == 'imageId,faceId,yaw' and set(rows[1:]) == expected and rows[1:] == sorted(rows[1:])
    assert progress.startswith('Face 4 of')
