"""Tests of face_luma.py and of the measured-light breakdown in score.py."""
import json
from pathlib import Path
import numpy as np
import pytest
from PIL import Image
import build_manifest as bm
import face_luma
import score

MANIFEST = Path(__file__).resolve().parents[1] / 'manifest'


def test_inside_takes_the_pixels_whose_centres_lie_in_the_box():
    assert list(face_luma.inside(0.6, 2.8)) == [1, 2]      # centres 1.5 and 2.5; 0.5 and 3.5 are outside
    assert list(face_luma.inside(1.5, 1.0)) == [1]         # a centre on the left edge is inside, on the right not
    assert list(face_luma.inside(0, 3)) == [0, 1, 2]


def test_mean_luma_uses_bt601_on_the_pixels_in_the_box():
    rgb = np.zeros((6, 8, 3))
    rgb[1:4, 2:5] = (200, 100, 50)
    luma = rgb @ face_luma.BT601
    assert face_luma.mean_luma(luma, {'imageId': 'a', 'faceId': '0', 'x': 2, 'y': 1, 'w': 3, 'h': 3}) == pytest.approx(
        0.299 * 200 + 0.587 * 100 + 0.114 * 50)
    half = face_luma.mean_luma(luma, {'imageId': 'a', 'faceId': '0', 'x': 3.6, 'y': 1, 'w': 2.8, 'h': 3})
    assert half == pytest.approx((0.299 * 200 + 0.587 * 100 + 0.114 * 50) / 2)  # columns 4 (inside) and 5 (outside)
    with pytest.raises(ValueError):
        face_luma.mean_luma(luma, {'imageId': 'a', 'faceId': '0', 'x': 1.6, 'y': 1, 'w': 0.5, 'h': 3})


def test_face_luma_writes_one_row_per_face(tmp_path):
    (tmp_path / 'manifest').mkdir()
    (tmp_path / 'images').mkdir()
    image = Image.new('RGB', (60, 40), (10, 10, 10))
    image.paste((240, 240, 240), (5, 5, 25, 25))
    image.save(tmp_path / 'images/a.png')
    bm.write_csv(tmp_path / 'manifest/images.csv', bm.IMAGE_COLUMNS,
                 [{'imageId': 'a', 'split': 'report', 'url': 'https://example.org/a.png', 'width': 40, 'height': 60,
                   'rotation': 90}])
    # In the upright image (turned 90 degrees counterclockwise) the bright square is at x 5..25, y 35..55.
    bm.write_csv(tmp_path / 'manifest/faces.csv', bm.FACE_COLUMNS,
                 [{'imageId': 'a', 'faceId': 0, 'x': 5, 'y': 35, 'w': 20, 'h': 20, 'isDepiction': 0},
                  {'imageId': 'a', 'faceId': 1, 'x': 30, 'y': 2, 'w': 8, 'h': 8, 'isDepiction': 0}])
    face_luma.main(['--manifest', str(tmp_path / 'manifest'), '--images', str(tmp_path / 'images')])
    luma = face_luma.read_luma(tmp_path / 'manifest/luma.csv')
    assert luma == {('a', '0'): pytest.approx(240), ('a', '1'): pytest.approx(10)}


def test_score_breaks_the_miss_rate_down_by_the_darkest_tenth(tmp_path):
    """20 faces in 20 images; the two darkest are missed, every other face is found."""
    (tmp_path / 'manifest').mkdir()
    ids = [f'{k:02d}' for k in range(20)]
    bm.write_csv(tmp_path / 'manifest/images.csv', bm.IMAGE_COLUMNS,
                 [{'imageId': i, 'split': 'report', 'width': 100, 'height': 100, 'rotation': 0} for i in ids])
    bm.write_csv(tmp_path / 'manifest/faces.csv', bm.FACE_COLUMNS,
                 [{'imageId': i, 'faceId': 0, 'x': 10, 'y': 10, 'w': 30, 'h': 30, 'isOccluded': 0, 'isTruncated': 0,
                   'isDepiction': 0, 'yaw': ''} for i in ids])
    bm.write_csv(tmp_path / 'manifest/luma.csv', face_luma.LUMA_COLUMNS,
                 [{'imageId': i, 'faceId': 0, 'meanLuma': 5 * k + (40 if k < 2 else 50)} for k, i in enumerate(ids)])
    run = [{'run': 'test'}] + [{'imageId': i, 'transform': 'none', 'inputSize': 640, 'tiling': {'kind': 'none'},
                                'boxes': [] if k < 2 else [[10, 10, 30, 30, 0.9]]} for k, i in enumerate(ids)]
    (tmp_path / 'run.jsonl').write_text(''.join(json.dumps(line) + '\n' for line in run))
    score.main([str(tmp_path / 'run.jsonl'), '--pad', '0', '--threshold', '0.5', '--manifest',
                str(tmp_path / 'manifest'), '--out', str(tmp_path / 'out.json'), '--faces', str(tmp_path / 'f.csv')])
    group = json.loads((tmp_path / 'out.json').read_text())['groups'][0]
    assert group['missRateBy']['luma']['darkest tenth']['value'] == 1 and group['missRateBy']['luma']['darkest tenth']['n'] == 2
    assert group['missRateBy']['luma']['rest']['value'] == 0 and group['lumaCutoff'] == 45
    flags = {r['imageId']: r['darkestTenth'] for r in bm.read_csv(tmp_path / 'f.csv')}
    assert [i for i, flag in flags.items() if flag == 'True'] == ['00', '01']

    rows = bm.read_csv(tmp_path / 'manifest/luma.csv')
    bm.write_csv(tmp_path / 'manifest/luma.csv', face_luma.LUMA_COLUMNS, rows[1:])
    with pytest.raises(SystemExit, match='does not match faces.csv'):
        score.main([str(tmp_path / 'run.jsonl'), '--pad', '0', '--threshold', '0.5', '--manifest',
                    str(tmp_path / 'manifest')])


def test_committed_luma_matches_the_committed_faces():
    faces = {(f['imageId'], f['faceId']) for f in bm.read_csv(MANIFEST / 'faces.csv')}
    luma = face_luma.read_luma(MANIFEST / 'luma.csv')
    assert set(luma) == faces and all(0 <= v <= 255 for v in luma.values())


def test_darkest_tenth_breaks_ties_by_image_and_face_id_and_refuses_an_empty_file(tmp_path):
    """10 faces, so the darkest tenth is one face; images 05 and 02 tie for the lowest luma, and 02 comes first."""
    (tmp_path / 'manifest').mkdir()
    ids = [f'{k:02d}' for k in range(10)]
    bm.write_csv(tmp_path / 'manifest/images.csv', bm.IMAGE_COLUMNS,
                 [{'imageId': i, 'split': 'report', 'width': 100, 'height': 100, 'rotation': 0} for i in ids])
    bm.write_csv(tmp_path / 'manifest/faces.csv', bm.FACE_COLUMNS,
                 [{'imageId': i, 'faceId': 0, 'x': 10, 'y': 10, 'w': 30, 'h': 30, 'isOccluded': 0, 'isTruncated': 0,
                   'isDepiction': 0, 'yaw': ''} for i in ids])
    bm.write_csv(tmp_path / 'manifest/luma.csv', face_luma.LUMA_COLUMNS,
                 [{'imageId': i, 'faceId': 0, 'meanLuma': 20 if i in ('02', '05') else 90} for i in ids])
    run = [{'run': 'test'}] + [{'imageId': i, 'transform': 'none', 'inputSize': 640, 'tiling': {'kind': 'none'},
                                'boxes': []} for i in ids]
    (tmp_path / 'run.jsonl').write_text(''.join(json.dumps(line) + '\n' for line in run))
    args = [str(tmp_path / 'run.jsonl'), '--pad', '0', '--threshold', '0.5', '--manifest', str(tmp_path / 'manifest')]
    score.main(args + ['--faces', str(tmp_path / 'f.csv')])
    assert [r['imageId'] for r in bm.read_csv(tmp_path / 'f.csv') if r['darkestTenth'] == 'True'] == ['02']
    bm.write_csv(tmp_path / 'manifest/luma.csv', face_luma.LUMA_COLUMNS, [])
    with pytest.raises(SystemExit, match='does not match faces.csv'):
        score.main(args)
