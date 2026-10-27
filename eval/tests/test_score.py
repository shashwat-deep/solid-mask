"""Tests of score.py and the geometry in transforms.py, on synthetic boxes."""
import csv, json
import numpy as np
import pytest
from PIL import Image
import build_manifest as bm
import score
import transforms

SQUARE = [(0, 0), (1, 0), (1, 1), (0, 1)]


def face(x, y, w, h, depiction='0', face_id='0', **flags):
    f = {'faceId': face_id, 'x': x, 'y': y, 'w': w, 'h': h, 'isDepiction': depiction, 'isOccluded': '0',
         'isTruncated': '0', 'yaw': ''}
    f.update(flags)
    f['size'] = score.size_bin(f, 200, 200)
    return f


def case(faces, boxes, transform='none', width=200, height=200):
    return score.Case('img', 'report', width, height, faces, transform, boxes)


def test_transforms_parse():
    assert transforms.parse('none') == ('none', 0.0)
    assert transforms.parse('rot45') == ('rot', 45.0) and transforms.parse('dark1.5') == ('dark', 1.5)
    with pytest.raises(ValueError):
        transforms.parse('blur3')


@pytest.mark.parametrize('size', [(101, 64), (64, 101), (80, 80)])
@pytest.mark.parametrize('degrees', [0, 15, 30, 45, 90, 135, 180, 270])
def test_rotation_matches_pillow(size, degrees):
    """Pillow's rotated canvas has the size rotated_size gives, and a pixel of a rotated patch is white exactly when
    its centre lies inside the patch's corners as rotate_points moves them."""
    w, h = size
    patch = (int(w * .3), int(h * .2), int(w * .55), int(h * .6))
    stored = Image.new('L', size)
    stored.paste(255, patch)
    turned = stored.rotate(degrees, expand=True)
    assert turned.size == transforms.rotated_size(w, h, degrees)
    polygon = transforms.rotate_points([(patch[0], patch[1]), (patch[2], patch[1]), (patch[2], patch[3]),
                                        (patch[0], patch[3])], w, h, degrees)
    cols, rows = np.meshgrid(np.arange(turned.width) + 0.5, np.arange(turned.height) + 0.5)
    margins = [(qx - px) * (rows - py) - (qy - py) * (cols - px)
               for (px, py), (qx, qy) in zip(polygon, polygon[1:] + polygon[:1])]
    inside = np.all([m >= 0 for m in margins], axis=0) | np.all([m <= 0 for m in margins], axis=0)
    on_edge = np.min(np.abs(margins), axis=0) < 1e-6
    white = np.asarray(turned) > 127
    assert not ((white != inside) & ~on_edge).any()


def test_clip_area_and_covered_area():
    assert score.area(SQUARE) == 1
    assert score.clip_area(SQUARE, 0.5, 0, 2, 2) == pytest.approx(0.5)
    assert score.clip_area(SQUARE, 2, 2, 3, 3) == 0
    diamond = [(1, 0), (2, 1), (1, 2), (0, 1)]
    assert score.area(diamond) == pytest.approx(2) and score.clip_area(diamond, 0, 0, 1, 2) == pytest.approx(1)
    box = [(0, 0), (10, 0), (10, 10), (0, 10)]
    assert score.covered_area(box, [(0, 0, 6, 10), (4, 0, 10, 10)]) == pytest.approx(100)  # overlap counted once
    assert score.covered_area(box, [(0, 0, 6, 10), (4, 0, 9, 10), (50, 50, 60, 60)]) == pytest.approx(90)
    assert score.covered_area(box, []) == 0


def test_mask_grows_rounds_outward_and_clips():
    assert score.mask((10.2, 5.7, 20, 10, 0.9), 0, 100, 50) == (10, 5, 31, 16)
    assert score.mask((10.7, 5.7, 20.1, 10.1, 0.9), 0, 100, 50) == (10, 5, 31, 16)  # down even past .5
    assert score.mask((10.2, 5.7, 20, 10, 0.9), 0.1, 100, 50) == (8, 4, 33, 17)
    assert score.mask((-3, -2, 10, 10, 0.9), 0, 100, 50) == (0, 0, 7, 8)
    assert score.mask((95, 45, 10, 10, 0.9), 0, 100, 50) == (95, 45, 100, 50)
    assert score.mask((120, 10, 10, 10, 0.9), 0, 100, 50) is None


def test_a_face_is_protected_from_90_percent_coverage():
    f = [face(50, 50, 100, 100)]

    def covered(width):
        c = case(f, [(50, 50, width, 100, 0.9)])
        return c.coverage(c.masks(0, 0.5))[0]

    assert covered(89.5) == pytest.approx(0.90)   # the mask rounds out to 90 pixels: protected
    assert covered(88.6) == pytest.approx(0.89)   # 89 pixels: missed
    c = case(f, [(50, 50, 89.5, 100, 0.9), (150, 150, 10, 10, 0.4)])
    assert c.coverage(c.masks(0, 0.5))[0] == pytest.approx(0.9) and len(c.masks(0, 0.4)) == 2


def test_found_is_one_to_one_in_order_of_score():
    a, b = face(0, 0, 10, 10, face_id='0'), face(6, 0, 10, 10, face_id='1')
    # The 0.6 box overlaps both faces equally (IoU 0.54); the 0.9 box is on face 0. Taken by score, the 0.9 box
    # takes face 0 and the 0.6 box takes face 1. Taken in file order, face 1 would stay unmatched.
    assert case([a, b], [(3, 0, 10, 10, 0.6), (0, 0, 10, 10, 0.9)]).found(0.5) == {0, 1}
    assert case([a, b], [(3, 0, 10, 10, 0.6), (0, 0, 10, 10, 0.9)]).found(0.7) == {0}
    assert case([a], [(0, 0, 10, 10, 0.9), (0.5, 0, 10, 10, 0.8)]).found(0.5) == {0}   # two boxes, one face
    assert case([a], [(0, 0, 20, 20, 0.9)]).found(0.5) == set()                         # IoU 0.25
    assert case([a], [(-5, 0, 10, 10, 0.9)]).found(0.5) == {0}  # clipped to the image: IoU 0.5


def test_false_masks():
    f = [face(0, 0, 10, 10), face(100, 100, 40, 40, depiction='1', face_id='1')]
    c = case(f, [(150, 10, 20, 20, 0.9), (100, 100, 40, 40, 0.9), (0, 0, 40, 40, 0.9), (0, 0, 10, 10, 0.9)])
    # far from every face: false; on the depiction: not false; IoU 100/1600 < 0.1 with the face: false
    assert c.false_masks(c.masks(0, 0.5)) == 2


def test_rotated_faces():
    f = [face(10, 10, 20, 30)]
    turned = case(f, [(10, 170, 30, 20, 0.9)], 'rot90', width=200, height=200)
    assert turned.polygons[0] == [(10, 190), (10, 170), (40, 170), (40, 190)]
    assert turned.coverage(turned.masks(0, 0.5))[0] == pytest.approx(1) and turned.found(0.5) == {0}
    tilted = case(f, [], 'rot45', width=200, height=100)
    assert (tilted.width, tilted.height) == Image.new('L', (200, 100)).rotate(45, expand=True).size
    assert tilted.areas[0] == pytest.approx(600)
    xs, ys = [p[0] for p in tilted.polygons[0]], [p[1] for p in tilted.polygons[0]]
    bbox = (min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys), 0.9)
    tilted = case(f, [bbox], 'rot45', width=200, height=100)
    # The box around a face turned 45 degrees covers it completely, yet its IoU with it is 600/1250 = 0.48: the
    # usual recall misses it, which is why the protocol counts coverage.
    assert tilted.coverage(tilted.masks(0, 0.5))[0] == pytest.approx(1) and tilted.found(0.5) == set()
    rect = (bbox[0], bbox[1], bbox[0] + bbox[2], bbox[1] + bbox[3])
    assert score.iou(rect, tilted.polygons[0], 600) == pytest.approx(0.48)


def test_bootstrap():
    boot = score.Bootstrap(4)
    everything = boot.ratio([2, 1, 3, 1], [2, 1, 3, 1])
    assert everything['value'] == 1 and everything['low'] == everything['high'] == 1 and everything['n'] == 7
    half = boot.ratio([1, 0, 1, 0], [2, 1, 1, 0])
    assert half['value'] == 0.5 and half['count'] == 2 and 0 <= half['low'] < 0.5 < half['high'] <= 1
    assert half['resamplesWithNoFaces'] > 0      # draws of image 4 only have no faces
    assert score.Bootstrap(4).ratio([1, 0, 1, 0], [2, 1, 1, 0]) == half   # seed 0 every time
    assert score.Bootstrap(0).ratio([], []) == {'value': None, 'count': 0, 'n': 0}


def write_manifest(folder, images, faces):
    folder.mkdir()
    bm.write_csv(folder / 'images.csv', bm.IMAGE_COLUMNS,
                 [{'imageId': i, 'split': split, 'width': w, 'height': h, 'rotation': 0}
                  for i, split, w, h in images])
    bm.write_csv(folder / 'faces.csv', bm.FACE_COLUMNS,
                 [{'imageId': i, 'faceId': n, 'x': x, 'y': y, 'w': w, 'h': h, 'isOccluded': occ, 'isTruncated': 0,
                   'isDepiction': dep, 'yaw': ''} for i, n, x, y, w, h, occ, dep in faces])


def write_detections(path, lines):
    run = {'run': 'test', 'model': 'stub', 'modelSha256': '0' * 64, 'ortVersion': 'none', 'backend': 'none',
           'threads': 1, 'nmsIoU': 0.3, 'browser': 'none', 'manifestSha256': '0' * 64}
    path.write_text('\n'.join(json.dumps(x) for x in [run] + lines) + '\n')


def line(image_id, boxes, transform='none'):
    return {'imageId': image_id, 'transform': transform, 'inputSize': 640, 'tiling': {'kind': 'none'},
            'boxes': boxes}


def test_main_scores_each_transform_and_setting(tmp_path, capsys):
    write_manifest(tmp_path / 'manifest', [('a', 'report', 400, 200), ('b', 'report', 400, 200),
                                           ('c', 'tune', 400, 200)],
                   [('a', 0, 10, 10, 100, 100, 0, 0), ('a', 1, 200, 20, 6, 6, 1, 0),
                    ('b', 0, 50, 50, 40, 40, 0, 1), ('c', 0, 0, 0, 10, 10, 0, 0)])
    write_detections(tmp_path / 'run.jsonl', [
        line('a', [[10, 10, 100, 100, 0.9], [300, 100, 20, 20, 0.7]]),   # face 0 found; one false mask
        line('b', [[50, 50, 40, 40, 0.2]]),                              # below the threshold: depiction missed
        line('c', [[0, 0, 10, 10, 0.9]]),                                # tune split: not scored
        line('a', [[10, 290, 100, 100, 0.9]], 'rot90'),           # face 0 of a, turned
    ])
    score.main([str(tmp_path / 'run.jsonl'), '--pad', '0', '--threshold', '0.5', '--manifest',
                str(tmp_path / 'manifest'), '--out', str(tmp_path / 'out.json'), '--faces', str(tmp_path / 'f.csv')])
    result = json.loads((tmp_path / 'out.json').read_text())
    none, rot = result['groups']
    assert (none['transform'], rot['transform']) == ('none', 'rot90') and none['imagesInSplit'] == 2
    assert none['images'] == 2 and none['faces'] == 2 and none['depictions'] == 1
    assert none['missRate']['value'] == 0.5 and none['missRate']['count'] == 1
    assert none['recallIoU50']['value'] == 0.5 and none['completeShare']['value'] == 0.5
    assert none['falseMasksPerImage']['value'] == 0.5 and none['depictionMissRate']['value'] == 1
    assert none['missRateBy']['size']['<2%']['value'] == 1 and none['missRateBy']['size']['>=25%']['value'] == 0
    assert none['missRateBy']['isOccluded']['1']['n'] == 1
    assert rot['images'] == 1 and rot['missRate']['value'] == 0.5
    with open(tmp_path / 'f.csv', newline='') as fh:
        assert len(list(csv.DictReader(fh))) == 3 + 2
    assert 'miss rate 0.5' in capsys.readouterr().err


def test_main_rejects_bad_detection_files(tmp_path):
    write_manifest(tmp_path / 'manifest', [('a', 'report', 100, 100)], [('a', 0, 0, 0, 10, 10, 0, 0)])
    args = ['--pad', '0', '--threshold', '0.5', '--manifest', str(tmp_path / 'manifest')]
    for lines, message in (([line('z', [])], 'not in the manifest'), ([line('a', []), line('a', [])], 'second line'),
                           ([line('a', [[1, 2, 3, 4]])], 'every box'), ([line('a', [], 'blur3')], 'unknown transform')):
        write_detections(tmp_path / 'run.jsonl', lines)
        with pytest.raises(SystemExit, match=message):
            score.main([str(tmp_path / 'run.jsonl')] + args)
    with pytest.raises(SystemExit):
        score.main([str(tmp_path / 'run.jsonl'), '--pad', '0', '--operating-point'])


def test_operating_point_follows_the_protocol_rule(tmp_path, capsys):
    """Boxes inset by 6 px in 100 px faces need pad 0.10 to cover them (0.05 grows them 4.4 px). Every image has
    one far box: at 0.30 or below that is one false mask per image; above 0.30 only image d's box (score 0.6)
    is left, 0.25 per image, which the rule allows. So the operating point is threshold 0.31 with pad 0.10."""
    names = 'abcd'
    write_manifest(tmp_path / 'manifest', [(i, 'tune', 400, 400) for i in names] + [('r', 'report', 400, 400)],
                   [(i, 0, 100, 100, 100, 100, 0, 0) for i in names + 'r'])
    write_detections(tmp_path / 'run.jsonl', [
        line(i, [[106, 106, 88, 88, 0.9], [300, 300, 30, 30, 0.6 if i == 'd' else 0.3]]) for i in names + 'r'])
    images, faces = score.load_manifest(tmp_path / 'manifest')
    _, groups = score.load_detections(tmp_path / 'run.jsonl', images, faces)
    tune = [c for c in next(iter(groups.values())) if c.split == 'tune']
    assert score.operating_point(tune) == (0.31, 0.1)
    score.main([str(tmp_path / 'run.jsonl'), '--operating-point', '--manifest', str(tmp_path / 'manifest'),
                '--out', str(tmp_path / 'op.json')])
    group = json.loads((tmp_path / 'op.json').read_text())['groups'][0]
    assert group['operatingPoint'] == {'threshold': 0.31, 'pad': 0.1} and group['images'] == 4
    assert group['missRate']['value'] == 0 and group['falseMasksPerImage']['value'] == 0.25
    assert score.operating_point([case([face(0, 0, 10, 10)], [(100, 100, 10, 10, 0.99)])]) is None
