"""Tests of check_files.py (check E2) on JPEG and PNG files made to carry each kind of hidden data."""
import io, json
from pathlib import Path
import numpy as np
import pytest
from PIL import Image, ImageCms, PngImagePlugin
import check_files

PICTURE = Image.fromarray(np.random.default_rng(4).integers(0, 256, (24, 32, 3), dtype=np.uint8), 'RGB')
SRGB = ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
LAB = ImageCms.ImageCmsProfile(ImageCms.createProfile('LAB')).tobytes()


def jpeg(**options):
    buffer = io.BytesIO()
    PICTURE.save(buffer, 'JPEG', quality=90, **options)
    return buffer.getvalue()


def with_segment(data, marker, payload):
    """data with a segment inserted right after the start-of-image marker."""
    return data[:2] + bytes([0xFF, marker]) + (len(payload) + 2).to_bytes(2, 'big') + payload + data[2:]


def png(**options):
    buffer = io.BytesIO()
    PICTURE.save(buffer, 'PNG', **options)
    return buffer.getvalue()


def report(tmp_path, files):
    paths = []
    for name, data in files.items():
        (tmp_path / name).write_bytes(data)
        paths.append(tmp_path / name)
    return {Path(e['file']).name: e for e in check_files.check(paths)['files']}


def test_a_plain_jpeg_passes_and_lists_its_segments(tmp_path):
    entry = report(tmp_path, {'plain.jpg': jpeg()})['plain.jpg']
    assert entry['pass'] and entry['segments'][0] == 'JFIF' and 'SOS' in entry['segments'] and entry['other'] == []


@pytest.mark.parametrize('name, data, problem', [
    ('exif.jpg', jpeg(exif=Image.Exif().tobytes() or b'Exif\x00\x00MM\x00*\x00\x00\x00\x08\x00\x00'), 'APP1 (EXIF)'),
    ('xmp.jpg', with_segment(jpeg(), 0xE1, b'http://ns.adobe.com/xap/1.0/\x00<x:xmpmeta/>'), 'APP1 (XMP)'),
    ('c2pa.jpg', with_segment(jpeg(), 0xEB, b'JP\x00\x01\x00\x00\x00\x01jumb'), 'APP11 (C2PA or other JUMBF)'),
    ('iptc.jpg', with_segment(jpeg(), 0xED, b'Photoshop 3.0\x008BIM\x04\x04'), 'APP13 (IPTC)'),
    ('thumb.jpg', with_segment(jpeg(), 0xE0, b'JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x01\x01' + bytes(3)),
     'JFIF with a thumbnail'),
    ('jfxx.jpg', with_segment(jpeg(), 0xE0, b'JFXX\x00\x13' + bytes(4)), 'JFXX (a thumbnail)'),
    ('jfif-extra.jpg', with_segment(jpeg(), 0xE0, b'JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00hello'),
     'JFIF with 5 bytes after its header'),
    ('jfif-short.jpg', with_segment(jpeg(), 0xE0, b'JFIF\x00\x01\x01'), 'JFIF cut short'),
    ('trailing.jpg', jpeg() + b'\xff\xd8 a second image', '17 bytes after the end of the image'),
], ids=lambda v: v if isinstance(v, str) and v.endswith('.jpg') else '')
def test_each_kind_of_hidden_data_fails(tmp_path, name, data, problem):
    entry = report(tmp_path, {name: data})[name]
    assert not entry['pass'] and problem in entry['problems']


def test_a_comment_or_unknown_segment_is_listed_for_the_authors(tmp_path):
    entry = report(tmp_path, {'comment.jpg': jpeg(comment=b'hello')})['comment.jpg']
    assert entry['pass'] and entry['other'] == ['COM (comment)']
    entry = report(tmp_path, {'adobe.jpg': with_segment(jpeg(), 0xEE, b'Adobe\x00\x64')})['adobe.jpg']
    assert entry['pass'] and entry['other'] == ['APP14 (Adobe)']


def test_icc_profiles_must_be_the_same_in_every_file(tmp_path):
    same = report(tmp_path, {'a.jpg': jpeg(icc_profile=SRGB), 'b.jpg': jpeg(icc_profile=SRGB)})
    assert all(e['pass'] for e in same.values()) and same['a.jpg']['icc'] == same['b.jpg']['icc']
    some = report(tmp_path, {'a.jpg': jpeg(icc_profile=SRGB), 'c.jpg': jpeg()})  # a profile only some files carry
    assert not some['a.jpg']['pass'] and some['c.jpg']['pass'] and '1 files have none' in some['a.jpg']['problems'][0]
    mixed = report(tmp_path, {'a.jpg': jpeg(icc_profile=SRGB), 'b.jpg': jpeg(icc_profile=LAB)})
    assert not mixed['a.jpg']['pass'] and not mixed['b.jpg']['pass']
    assert any('ICC profile' in p for p in mixed['b.jpg']['problems'])


def test_broken_files_fail_without_stopping_the_run(tmp_path):
    entries = report(tmp_path, {'cut.jpg': jpeg()[:-200], 'junk.jpg': b'not an image', 'ok.jpg': jpeg()})
    assert not entries['cut.jpg']['pass'] and entries['cut.jpg']['problems'][0].startswith('not a well-formed JPEG')
    assert not entries['junk.jpg']['pass'] and entries['ok.jpg']['pass']


def test_png_chunks(tmp_path):
    text = PngImagePlugin.PngInfo()
    text.add_text('Comment', 'taken at home')
    entries = report(tmp_path, {'plain.png': png(), 'text.png': png(pnginfo=text),
                                'exif.png': png(exif=b'MM\x00*\x00\x00\x00\x08\x00\x00'),
                                'trailing.png': png() + b'more'})
    assert entries['plain.png']['pass'] and entries['plain.png']['segments'][0] == 'IHDR'
    assert 'text (tEXt)' in entries['text.png']['problems'] and 'EXIF (eXIf)' in entries['exif.png']['problems']
    assert '4 bytes after the end of the image' in entries['trailing.png']['problems']
    broken = bytearray(png())
    broken[45] ^= 0xFF  # inside the first IDAT chunk's data (after IHDR, IDAT's length and type): wrong CRC
    entry = report(tmp_path, {'broken.png': bytes(broken)})['broken.png']
    assert not entry['pass'] and 'CRC' in entry['problems'][0]


def test_main_searches_folders_writes_the_report_and_exits_on_failure(tmp_path, capsys):
    (tmp_path / 'saved').mkdir()
    (tmp_path / 'saved/masked-1.jpg').write_bytes(jpeg())
    (tmp_path / 'saved/notes.txt').write_text('not checked')
    check_files.main([str(tmp_path / 'saved'), '--out', str(tmp_path / 'e2.json')])
    assert json.loads((tmp_path / 'e2.json').read_text())['passed'] == 1
    (tmp_path / 'saved/masked-2.jpg').write_bytes(jpeg(exif=b'Exif\x00\x00MM\x00*\x00\x00\x00\x08\x00\x00'))
    with pytest.raises(SystemExit):
        check_files.main([str(tmp_path / 'saved')])
    assert 'FAIL' in capsys.readouterr().out
