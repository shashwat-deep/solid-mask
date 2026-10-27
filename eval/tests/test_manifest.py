"""Tests of build_manifest.py, download.py and review_sheet.py, on made-up data served from this computer, and
checks that the committed manifest follows the rules in build_manifest.py."""
import csv, hashlib, io
from pathlib import Path
import numpy as np
import pytest
from PIL import Image
import build_manifest as bm
import download
import review_sheet

MANIFEST = Path(__file__).resolve().parents[1] / 'manifest'
BOX = (0.25, 0.5, 0.1, 0.4)  # x_min, x_max, y_min, y_max of the made-up faces


def white_patch(size, box):
    """A black greyscale image with the normalised box painted white."""
    im = Image.new('L', size)
    w, h = size
    im.paste(255, (round(box[0] * w), round(box[2] * h), round(box[1] * w), round(box[3] * h)))
    return im


def test_upright_matches_pillow_turning_the_image_counterclockwise():
    stored = white_patch((60, 40), BOX)
    for rotation in (0, 90, 180, 270):
        turned = stored.rotate(rotation, expand=True)
        x0, x1, y0, y1 = bm.upright(*BOX, rotation)
        w, h = turned.size
        assert turned.getbbox() == (round(x0 * w), round(y0 * h), round(x1 * w), round(y1 * h))
    with pytest.raises(ValueError):
        bm.upright(*BOX, 45)


def test_split_and_rank_depend_only_on_the_image_id():
    assert bm.digest('order', 'abc') == hashlib.sha256(b'solid-mask:order:0:abc').hexdigest()
    ids = [f'{n:016x}' for n in range(5000)]
    assert 0.18 < sum(bm.split_of(i) == 'tune' for i in ids) / len(ids) < 0.22


def test_eligible_leaves_out_group_of_unknown_orientation_and_other_licences():
    ok = {'License': bm.LICENCE, 'Rotation': '90.0'}
    boxes = {i: [{'IsGroupOf': '0'}] for i in 'abcde'}
    boxes['b'].append({'IsGroupOf': '1'})
    info = {'a': ok, 'b': ok, 'c': {**ok, 'Rotation': ''}, 'd': {**ok, 'License': 'other'}}  # e has no metadata
    assert bm.eligible(boxes, info) == ['a']


def test_select_replaces_a_removed_image_with_the_next_one_in_its_split():
    ids = [f'{n:016x}' for n in range(200)]
    first = bm.select(ids, {}, 3, 5)
    tune = [i for i, split in first if split == 'tune']
    second = bm.select(ids, {tune[0]: 'remove', tune[1]: 'keep'}, 3, 5)
    assert [i for i, split in second if split == 'tune'][:2] == tune[1:]
    assert tune[0] not in {i for i, _ in second}
    assert [x for x in first if x[1] == 'report'] == [x for x in second if x[1] == 'report']
    with pytest.raises(SystemExit):
        bm.select(ids, {i: 'remove' for i in ids}, 1, 0)


def test_read_review_checks_every_row(tmp_path):
    path = tmp_path / 'review.csv'
    assert bm.read_review(path) == {}
    good = [{'imageId': 'a', 'decision': 'keep', 'reason': '', 'reviewer': 'S'},
            {'imageId': 'b', 'decision': 'remove', 'reason': 'unboxed-face', 'reviewer': 'S'}]
    bm.write_csv(path, bm.REVIEW_COLUMNS, good)
    assert bm.read_review(path) == {'a': 'keep', 'b': 'remove'}
    for bad in ({'decision': 'remove', 'reason': ''}, {'decision': 'keep', 'reason': 'intimate'},
                {'decision': 'remove', 'reason': 'blurry'}, {'reviewer': ''}, {'imageId': 'a'}):
        bm.write_csv(path, bm.REVIEW_COLUMNS, good + [{**good[1], 'imageId': 'c', **bad}])
        with pytest.raises(SystemExit):
            bm.read_review(path)


def test_fetch_keeps_a_good_copy_and_replaces_a_damaged_one(site, tmp_path):
    base, folder, requested = site
    (folder / 'a.jpg').write_bytes(b'abc')
    good, dest = hashlib.sha256(b'abc').hexdigest(), tmp_path / 'out/a.jpg'
    assert download.fetch(f'{base}/a.jpg', dest, good) == good and dest.read_bytes() == b'abc'
    assert download.fetch(f'{base}/a.jpg', dest, good) == good and len(requested) == 1
    dest.write_bytes(b'abd')
    assert download.fetch(f'{base}/a.jpg', dest, good) == good and dest.read_bytes() == b'abc'
    with pytest.raises(ValueError):
        download.fetch(f'{base}/a.jpg', tmp_path / 'out/b.jpg', '0' * 64)
    assert not (tmp_path / 'out/b.jpg').exists() and not (tmp_path / 'out/b.jpg.part').exists()
    with pytest.raises(OSError):
        download.fetch(f'{base}/missing.jpg', tmp_path / 'out/c.jpg')


def test_download_lists_every_failure(site, tmp_path, capsys):
    base, folder, _ = site
    (folder / 'a.jpg').write_bytes(b'abc')
    (folder / 'b.jpg').write_bytes(b'changed')
    rows = [{'imageId': 'a', 'url': f'{base}/a.jpg', 'sha256': hashlib.sha256(b'abc').hexdigest()},
            {'imageId': 'b', 'url': f'{base}/b.jpg', 'sha256': hashlib.sha256(b'b').hexdigest()},
            {'imageId': 'c', 'url': f'{base}/c.jpg', 'sha256': hashlib.sha256(b'c').hexdigest()}]
    bm.write_csv(tmp_path / 'images.csv', ['imageId', 'url', 'sha256'], rows)
    with pytest.raises(SystemExit, match='2 images failed'):
        download.main([str(tmp_path / 'images.csv'), '--out', str(tmp_path / 'out')])
    err = capsys.readouterr().err
    assert '  b: ValueError' in err and '  c: HTTPError' in err
    assert (tmp_path / 'out/a.jpg').read_bytes() == b'abc'


def make_open_images(base, folder, n=40):
    """Made-up Open Images metadata and images: n images with one face each, rotations 0, 90, 180 and 270 in
    turn, plus one image each with a group-of face, an unknown orientation and another licence. Returns META."""
    bbox = ['ImageID,Source,LabelName,Confidence,XMin,XMax,YMin,YMax,IsOccluded,IsTruncated,IsGroupOf,IsDepiction,'
            'IsInside']
    info = ['ImageID,Subset,OriginalURL,OriginalLandingURL,License,AuthorProfileURL,Author,Title,OriginalSize,'
            'OriginalMD5,Thumbnail300KURL,Rotation']
    (folder / 'validation').mkdir()
    for n_ in range(n + 3):
        i = f'{n_:016x}'
        group, rotation, licence = n_ == n, ('', '0.0', '90.0', '180.0', '270.0')[(n_ % 4 + 1) * (n_ != n + 1)], (
            bm.LICENCE if n_ != n + 2 else 'https://creativecommons.org/licenses/by-nc/2.0/')
        bbox.append(f'{i},xclick,{bm.FACE},1,{BOX[0]},{BOX[1]},{BOX[2]},{BOX[3]},0,0,{int(group)},0,0')
        bbox.append(f'{i},xclick,/m/01g317,1,0,1,0,1,0,0,0,0,0')  # a "Person" box, which is not a face
        info.append(f'{i},validation,https://example.org/{i}_o.jpg,https://example.org/{i},{licence},'
                    f'https://example.org/people/{n_},"Author, {n_}","A ""title"", {n_}",1,x,,{rotation}')
        buffer = io.BytesIO()
        white_patch((80, 60), BOX).convert('RGB').save(buffer, 'JPEG', quality=100)
        (folder / 'validation' / f'{i}.jpg').write_bytes(buffer.getvalue())
    files = {'validation-annotations-bbox.csv': bbox, 'test-annotations-bbox.csv': bbox[:1],
             'validation-images-with-rotation.csv': info, 'test-images-with-rotation.csv': info[:1],
             'oidv7-class-descriptions-boxable.csv': ['/m/01g317,Person', f'{bm.FACE},Human face']}
    meta = {}
    for name, lines in files.items():
        data = ('\n'.join(lines) + '\n').encode()
        (folder / name).write_bytes(data)
        meta[name] = (f'{base}/{name}', hashlib.sha256(data).hexdigest())
    return meta


def test_build_manifest_end_to_end(site, tmp_path, monkeypatch):
    base, folder, _ = site
    monkeypatch.setattr(bm, 'META', make_open_images(base, folder))
    monkeypatch.setattr(bm, 'CVDF', base + '/{subset}/{image_id}.jpg')
    paths = ['--meta', str(tmp_path / 'meta'), '--images', str(tmp_path / 'images'),
             '--manifest', str(tmp_path / 'manifest')]
    bm.main(['--tune', '2', '--report', '4'] + paths)
    images = bm.read_csv(tmp_path / 'manifest/images.csv')
    faces = {r['imageId']: r for r in bm.read_csv(tmp_path / 'manifest/faces.csv')}
    assert [r['split'] for r in images].count('tune') == 2 and len(images) == len(faces) == 6
    assert {'90', '270'} & {r['rotation'] for r in images} and len({r['rotation'] for r in images}) >= 3
    assert not {'0000000000000028', '0000000000000029', '000000000000002a'} & set(faces)  # the three left out
    for image in images:
        i, rotation = image['imageId'], int(image['rotation'])
        assert image['author'].startswith('Author, ') and image['title'].startswith('A "title", ')
        assert image['sha256'] == hashlib.sha256((folder / 'validation' / f'{i}.jpg').read_bytes()).hexdigest()
        assert (int(image['width']), int(image['height'])) == ((80, 60) if rotation in (0, 180) else (60, 80))
        upright = Image.open(tmp_path / 'images' / f'{i}.jpg').convert('L').rotate(rotation, expand=True)
        rows, cols = np.nonzero(np.asarray(upright) > 128)
        x, y, w, h = (float(faces[i][k]) for k in 'xywh')
        assert np.allclose([cols.min(), rows.min(), cols.max() + 1, rows.max() + 1], [x, y, x + w, y + h], atol=1)
        assert faces[i]['xMinNorm'] == str(BOX[0]) and faces[i]['yaw'] == ''

    tune = [r['imageId'] for r in images if r['split'] == 'tune']
    labelled = bm.read_csv(tmp_path / 'manifest/faces.csv')
    for row in labelled:
        row['yaw'] = 'profile' if row['imageId'] == tune[1] else ''
    bm.write_csv(tmp_path / 'manifest/faces.csv', bm.FACE_COLUMNS, labelled)
    bm.write_csv(tmp_path / 'manifest/review.csv', bm.REVIEW_COLUMNS,
                 [{'imageId': tune[0], 'decision': 'remove', 'reason': 'doubtful', 'reviewer': 'S'}])
    bm.main(['--tune', '2', '--report', '4'] + paths)
    images = bm.read_csv(tmp_path / 'manifest/images.csv')
    after = [r['imageId'] for r in images if r['split'] == 'tune']
    assert tune[0] not in after and tune[1] in after and len(after) == 2
    assert {r['imageId']: r['yaw'] for r in bm.read_csv(tmp_path / 'manifest/faces.csv')}[tune[1]] == 'profile'

    review_sheet.main(['--all', '--manifest', str(tmp_path / 'manifest'), '--images', str(tmp_path / 'images'),
                       '--out', str(tmp_path / 'review')])
    page = (tmp_path / 'review/index.html').read_text(encoding='utf-8')
    assert page.count('<figure>') == 6 and page.count('<select') == 6
    assert all((tmp_path / 'review' / f'{r["imageId"]}.jpg').exists() for r in images)


def test_committed_manifest_follows_the_rules():
    images = bm.read_csv(MANIFEST / 'images.csv')
    faces = bm.read_csv(MANIFEST / 'faces.csv')
    review = bm.read_review(MANIFEST / 'review.csv')
    by_id = {r['imageId']: r for r in images}
    assert len(by_id) == len(images) and list(images[0]) == bm.IMAGE_COLUMNS and list(faces[0]) == bm.FACE_COLUMNS
    assert all(review.get(i) != 'remove' for i in by_id)
    for r in images:
        assert r['split'] == bm.split_of(r['imageId']) and r['licence'] == bm.LICENCE
        assert len(r['sha256']) == 64 and int(r['rotation']) in (0, 90, 180, 270)
    assert sum(r['split'] == 'tune' for r in images) == 200 and sum(r['split'] == 'report' for r in images) == 800
    for f in faces:
        image = by_id[f['imageId']]
        x0, x1, y0, y1 = bm.upright(*(float(f[k]) for k in ('xMinNorm', 'xMaxNorm', 'yMinNorm', 'yMaxNorm')),
                                    int(image['rotation']))
        expected = [x0 * int(image['width']), y0 * int(image['height']), (x1 - x0) * int(image['width']),
                    (y1 - y0) * int(image['height'])]
        assert np.allclose([float(f[k]) for k in 'xywh'], expected, atol=0.002)
    assert {f['imageId'] for f in faces} == set(by_id)
