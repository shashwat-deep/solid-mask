"""Tests of yaw_sheet.py and yaw_agreement.py on made-up faces and labels."""
import json
import numpy as np
import pytest
from PIL import Image
import build_manifest as bm
import download
import yaw_agreement
import yaw_sheet

LABELLERS = ['ann', 'bob']


def make_manifest(folder, n_images=30, faces_per_image=3):
    """Made-up images (grey, with a white square per face), their faces, every third of them a depiction, and a
    review that keeps every image."""
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
    bm.write_csv(folder / 'manifest/review.csv', bm.REVIEW_COLUMNS,
                 [{'imageId': r['imageId'], 'decision': 'keep', 'reason': '', 'reviewer': 'test'} for r in images])
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
    (tmp_path / 'yaw/ann').mkdir(parents=True)
    for name in ('0000000000000000_9.jpg', 'holiday.jpg', 'notes.txt'):  # a crop of an earlier build, and others
        (tmp_path / 'yaw/ann' / name).write_text('x')
    yaw_sheet.main(args + ['--labeller', 'ann'])
    page = (tmp_path / 'yaw/ann/index.html').read_text(encoding='utf-8')
    shown = json.loads(page.split('const faces = ', 1)[1].split(';\n', 1)[0])
    assert len(shown) == len(chosen) - 5 and not {(f['imageId'], f['faceId']) for f in shown} & set(done)
    assert sorted(p.name for p in (tmp_path / 'yaw/ann').iterdir()) == sorted(
        [f['src'] for f in shown] + ['holiday.jpg', 'index.html', 'notes.txt'])
    assert 'bob' not in page and f'<h2>{tmp_path / "labels" / "yaw-ann.csv"}</h2>' in page
    review = bm.read_csv(tmp_path / 'manifest/review.csv')
    review[3].update(decision='remove', reason='doubtful')
    bm.write_csv(tmp_path / 'manifest/review.csv', bm.REVIEW_COLUMNS, review[:3] + review[4:] + [review[3]])
    with pytest.raises(SystemExit, match='1 of the 30 images'):  # removed, so the set is not frozen yet
        yaw_sheet.main(args + ['--labeller', 'ann'])
    bm.write_csv(tmp_path / 'manifest/review.csv', bm.REVIEW_COLUMNS, review[:3] + review[4:])
    with pytest.raises(SystemExit, match='1 of the 30 images'):  # not reviewed yet
        yaw_sheet.main(args + ['--labeller', 'ann'])
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


def test_agreement_reports_kappa_and_keeps_settled_labels(tmp_path, capsys, monkeypatch):
    args = make_manifest(tmp_path) + ['--labellers', *LABELLERS]
    images, faces = manifest_rows(tmp_path)
    chosen = [(f['imageId'], f['faceId']) for f in yaw_sheet.sample(images, faces)]
    rng = np.random.default_rng(0)
    ann = {face: yaw_sheet.LABELS[k] for face, k in zip(chosen, rng.integers(0, 3, len(chosen)))}
    bob = dict(ann)
    for face in chosen[:6]:
        bob[face] = 'unclear'
    write_labels(tmp_path, 'ann', ann)
    with pytest.raises(SystemExit, match='yaw-bob.csv does not exist; once you have both finished'):
        yaw_agreement.main(args)
    write_labels(tmp_path, 'bob', {face: label for face, label in bob.items() if face != chosen[-1]})
    with pytest.raises(SystemExit, match='1 faces of the sample unlabelled'):
        yaw_agreement.main(args)
    write_labels(tmp_path, 'bob', {**bob, ('removed-in-review', '0'): 'frontal'})

    disagreements_file = tmp_path / 'labels/yaw-disagreements.csv'  # the commit is read before the script writes
    monkeypatch.setattr(yaw_agreement.run_detect, 'git_commit', lambda: f'written: {disagreements_file.exists()}')
    yaw_agreement.main(args)
    summary = json.loads((tmp_path / 'labels/agreement.json').read_text())  # beside the labels by default
    assert summary['gitCommit'] == 'written: False'
    assert summary['labelsOutsideSample'] == {'ann': 0, 'bob': 1}
    assert summary['labelsSha256'] == {name: download.sha256_file(tmp_path / f'labels/yaw-{name}.csv')
                                       for name in LABELLERS}
    assert summary['disagreementsSha256'] == download.sha256_file(tmp_path / 'labels/yaw-disagreements.csv')
    assert summary['numpy'] == np.__version__ and summary['python']
    assert summary['faces'] == len(chosen) and summary['disagreements'] == 6 == summary['unsettled']
    assert summary['observedAgreement'] == pytest.approx(1 - 6 / len(chosen))
    assert 0 < summary['kappa']['low'] <= summary['kappa']['value'] <= summary['kappa']['high'] <= 1
    assert summary['kappaWithoutUnclear']['value'] == 1 and summary['kappaWithoutUnclear']['faces'] == len(chosen) - 6
    assert summary['counts']['bob']['unclear'] == 6 + list(ann.values()).count('unclear')
    with pytest.raises(SystemExit, match='not settled'):
        yaw_agreement.main(args + ['--write'])

    disagreements = bm.read_csv(tmp_path / 'labels/yaw-disagreements.csv')
    assert list(disagreements[0]) == ['imageId', 'faceId', 'ann', 'bob', 'settled']
    for row in disagreements:
        row['settled'] = row['ann']
    bm.write_csv(tmp_path / 'labels/yaw-disagreements.csv', list(disagreements[0]), disagreements)
    yaw_agreement.main(args[:-3] + ['--labellers', 'bob', 'ann'])  # a rerun, in either order, keeps what was settled
    assert all(r['settled'] for r in bm.read_csv(tmp_path / 'labels/yaw-disagreements.csv'))
    faces_sha = download.sha256_file(tmp_path / 'manifest/faces.csv')
    yaw_agreement.main(args + ['--write', '--out', str(tmp_path / 'final.json')])
    assert json.loads((tmp_path / 'final.json').read_text())['manifestSha256']['faces.csv'] == faces_sha  # as read
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
        page.keyboard.down('1')
        page.keyboard.down('1')  # held down: the browser repeats the key, which labels nothing more
        page.keyboard.up('1')
        for key in ('Control+2', 'Alt+3', 'Meta+4'):
            page.keyboard.press(key)
        page.get_by_role('button', name='3 profile').click()
        for key in (' ', 'Enter'):  # these would press a button that kept the focus
            page.keyboard.press(key)
        text = page.locator('#csv').input_value()
        progress = page.locator('#progress').inner_text()
        copied = page.evaluate("""() => {
          const box = document.getElementById('csv'), saved = [];
          for (const end of [5, box.value.length]) {
            box.setSelectionRange(0, end);
            box.dispatchEvent(new Event('copy'));
            saved.push(!unsaved);
          }
          return saved;
        }""")
        browser.close()
    rows = text.strip().split('\n')
    expected = {f'{chosen[0]["imageId"]},{chosen[0]["faceId"]},profile',
                f'{chosen[1]["imageId"]},{chosen[1]["faceId"]},frontal',
                f'{chosen[2]["imageId"]},{chosen[2]["faceId"]},three-quarter',
                f'{chosen[3]["imageId"]},{chosen[3]["faceId"]},unclear',
                f'{chosen[4]["imageId"]},{chosen[4]["faceId"]},frontal',
                f'{chosen[5]["imageId"]},{chosen[5]["faceId"]},profile'}
    assert rows[0] == 'imageId,faceId,yaw' and set(rows[1:]) == expected and rows[1:] == sorted(rows[1:])
    assert progress.startswith('Face 6 of')
    assert copied == [False, True]  # only a copy of the whole box counts as saved
