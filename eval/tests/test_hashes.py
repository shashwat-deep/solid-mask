"""Tests of pdq.py, render_copies.py and hash_distance.py (check E3)."""
import io, json
from pathlib import Path
import numpy as np
import pytest
from PIL import Image
import build_manifest as bm
import download
import hash_distance
import pdq
import render_copies
import run_detect
from test_run_detect import FACES, UPRIGHT, keep_all, make_test_set

REFERENCE = Path(__file__).resolve().parent / 'pdq_reference.csv'
ROOT = Path(__file__).resolve().parents[2]


def noise(seed, shape=(96, 128, 3)):
    return np.random.default_rng(seed).integers(0, 256, shape, dtype=np.uint8)


def test_box_filter_is_the_mean_of_its_window():
    values = np.random.default_rng(0).random((50, 7)).astype(np.float32) * 255
    for size in (1, 2, 5, 8):
        half = (size + 2) // 2
        out = pdq.box(values, size)
        for k in range(50):
            window = values[max(0, k - (size - half)):min(50, k + half)]
            assert np.allclose(out[k], window.mean(axis=0), atol=1e-3), (size, k)


def test_hash_has_256_bits_half_of_them_set():
    digest, quality = pdq.hash_luma(pdq.luma(noise(1)))
    assert len(digest) == 64 and bin(int(digest, 16)).count('1') == 128 and quality == 100
    assert pdq.hash_luma(np.full((80, 80), 100, np.float32))[1] == 0       # a flat picture has no quality
    with pytest.raises(ValueError):
        pdq.hash_luma(np.zeros((4, 80), np.float32))


def test_distance_reflects_how_much_a_picture_changed():
    image = Image.fromarray(np.asarray(Image.fromarray(noise(2)).resize((400, 300), Image.Resampling.BILINEAR)))
    buffer = io.BytesIO()
    image.save(buffer, 'JPEG', quality=80)
    recompressed = Image.open(io.BytesIO(buffer.getvalue()))
    original, _ = pdq.hash_image(image)
    assert pdq.distance(original, pdq.hash_image(image)[0]) == 0
    assert pdq.distance(original, pdq.hash_image(recompressed)[0]) <= pdq.MATCH_DISTANCE
    assert pdq.distance(original, pdq.hash_image(Image.fromarray(noise(3, (300, 400, 3))))[0]) > 64
    assert pdq.distance('f' * 64, '0' * 64) == 256


def test_hash_image_shrinks_to_512_keeping_the_shape():
    image = Image.fromarray(noise(4, (512, 1024, 3)))
    small = image.copy()
    small.thumbnail((512, 512))
    assert small.size == (512, 256) and pdq.hash_image(image) == pdq.hash_luma(pdq.luma(np.asarray(small)))


def test_pdq_matches_metas_reference_hashes(tmp_path):
    """The eight images of Meta's PDQ regression test, with the hashes its C++ reference prints. The C++ tool
    stretches an image larger than 512 pixels to 512 x 512 by nearest neighbour first; given those pixels, the hash
    must be the very same. The images are downloaded once into data/pdq-reference/, which git ignores, and reused."""
    folder = ROOT / 'data/pdq-reference'
    rows = bm.read_csv(REFERENCE)
    done, failed = download.fetch_all([(r['file'], r['url'], folder / r['file'], r['sha256']) for r in rows])
    if failed:
        pytest.skip(f'cannot download Meta\'s PDQ test images: {next(iter(failed.values()))}')
    for r in rows:
        rgb = np.asarray(Image.open(folder / r['file']).convert('RGB'))
        h, w = rgb.shape[:2]
        if h > 512 or w > 512:
            rgb = rgb[np.ix_((np.arange(512) * (h / 512)).astype(int), (np.arange(512) * (w / 512)).astype(int))]
        digest, quality = pdq.hash_luma(pdq.luma(rgb))
        assert (digest, quality) == (r['pdq'], int(r['quality'])), r['file']


def textured_jpeg(rotation):
    """The made-up photo of test_run_detect on a textured grey background, which gives PDQ something to hash (the
    flat background gives it nothing), stored turned like stored_jpeg(). Grey is never the stub's magenta."""
    texture = Image.fromarray(np.random.default_rng(5).integers(0, 256, (24, 32), dtype=np.uint8), 'L')
    photo = texture.resize(UPRIGHT, Image.Resampling.BICUBIC).convert('RGB')
    for x, y, w, h in FACES:
        photo.paste((255, 0, 255), (x, y, x + w, y + h))
    buffer = io.BytesIO()
    photo.rotate(-rotation, expand=True).save(buffer, 'JPEG', quality=100, subsampling=0)
    return buffer.getvalue()


def stub_detections(tmp_path):
    args = make_test_set(tmp_path)
    run_detect.main(args + ['--run-id', 'd'])
    return args, tmp_path / 'out/d.jsonl'


def test_render_copies_masks_the_faces_and_keeps_a_plain_copy(chromium, tmp_path):
    args, detections = stub_detections(tmp_path)
    paths = ['--manifest', args[1], '--images', args[3], '--out', str(tmp_path / 'rendered')]
    render_copies.main([str(detections), '--pad', '0', '--threshold', '0.5', '--split', 'all', '--render-id', 'r']
                       + paths)
    folder = tmp_path / 'rendered/r'
    info = json.loads((folder / 'render_info.json').read_text())
    assert info['pad'] == 0 and sorted(info['images']) == ['r000', 'r090', 'r180', 'r270']
    for i, entry in info['images'].items():
        assert sorted(tuple(m) for m in entry['masks']) == sorted((x, y, x + w, y + h) for x, y, w, h in FACES)
        masked = np.asarray(Image.open(folder / f'{i}.masked.jpg').convert('RGB')).astype(int)
        plain = np.asarray(Image.open(folder / f'{i}.plain.jpg').convert('RGB')).astype(int)
        assert masked.shape[:2] == plain.shape[:2] == (UPRIGHT[1], UPRIGHT[0])
        for x, y, w, h in FACES:  # 16 px in, every 16 x 16 block lies wholly inside the face (as in the privacy suite)
            assert masked[y + 16:y + h - 16, x + 16:x + w - 16].max() <= 2      # black where the faces were
            assert plain[y + 16:y + h - 16, x + 16:x + w - 16, 0].min() > 200   # still magenta in the control
        assert download.sha256_file(folder / f'{i}.masked.jpg') == entry['maskedSha256']
    with pytest.raises(SystemExit, match='exists'):
        render_copies.main([str(detections), '--pad', '0', '--threshold', '0.5', '--split', 'all', '--render-id', 'r']
                           + paths)
    with pytest.raises(SystemExit, match='before it is reviewed'):
        render_copies.main([str(detections), '--pad', '0', '--threshold', '0.5', '--split', 'all', '--render-id', 's',
                            '--page', 'http://127.0.0.1:9/index.html'] + paths)


def test_hash_distance_reports_the_protocol_numbers(chromium, tmp_path, monkeypatch):
    import test_run_detect
    monkeypatch.setattr(test_run_detect, 'stored_jpeg', textured_jpeg)
    args, detections = stub_detections(tmp_path)
    render_copies.main([str(detections), '--pad', '0', '--threshold', '0.5', '--split', 'all', '--render-id', 'r',
                        '--manifest', args[1], '--images', args[3], '--out', str(tmp_path / 'rendered')])
    folder = tmp_path / 'rendered/r'
    hash_distance.main([str(folder), '--manifest', args[1], '--images', args[3]])
    report = json.loads((folder / 'e3.json').read_text())
    share = sum(w * h for _, _, w, h in FACES) / (UPRIGHT[0] * UPRIGHT[1])
    rows = bm.read_csv(folder / 'e3.csv')
    assert report['images'] == 4 and all(abs(float(r['maskedShare']) - share) < 1e-6 for r in rows)
    assert {r['maskedBin'] for r in rows} == {'5-10%'}
    assert report['withinPdq31Plain']['value'] == 1 and report['withinPdq31PlainBy']['5-10%']['n'] == 4
    assert all(int(r['pdqPlain']) <= int(r['pdqMasked']) for r in rows)
    assert set(report['pdqMasked']) == {'median', 'quartiles', 'histogram'} and report['lowQualityOriginals'] == 0
    with pytest.raises(SystemExit):  # a stub's copies never report into results/
        hash_distance.main([str(folder), '--manifest', args[1], '--images', args[3],
                            '--out', str(ROOT / 'results/privacy/e3-test.json')])
    rows = bm.read_csv(Path(args[1]) / 'images.csv')
    bm.write_csv(Path(args[1]) / 'images.csv', list(rows[0]), rows[:-1])  # the manifest changes after rendering
    with pytest.raises(SystemExit, match='render them again'):
        hash_distance.main([str(folder), '--manifest', args[1], '--images', args[3]])


def test_masked_share_counts_overlapping_masks_once():
    assert hash_distance.masked_share([[0, 0, 10, 10], [5, 0, 15, 10]], 100, 10) == pytest.approx(0.15)
    assert hash_distance.masked_bin(0) == 'no mask' and hash_distance.masked_bin(0.0099) == 'under 1%'
    assert hash_distance.masked_bin(0.25) == '25% and over'
