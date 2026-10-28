"""Tests of the image transforms in transforms.py: rotation, darkening with sensor noise, and the upright sRGB image
they start from."""
import base64, io
import numpy as np
import pytest
from PIL import Image, ImageCms
import build_manifest as bm
import check_colour
import transforms


def jpeg(image, **options):
    buffer = io.BytesIO()
    image.save(buffer, 'JPEG', quality=100, subsampling=0, **options)
    return buffer


@pytest.mark.parametrize('degrees', [0, 15, 30, 45, 90, 135, 180])
def test_rotate_matches_the_rotated_box_and_fills_the_corners(degrees):
    w, h = 101, 64
    patch = (30, 12, 55, 38)
    image = Image.new('RGB', (w, h), (0, 0, 0))
    image.paste((255, 255, 255), patch)
    turned = transforms.rotate(image, degrees)
    assert turned.size == transforms.rotated_size(w, h, degrees)
    corners = transforms.rotate_points([(patch[0], patch[1]), (patch[2], patch[1]), (patch[2], patch[3]),
                                        (patch[0], patch[3])], w, h, degrees)
    rows, cols = np.nonzero(np.asarray(turned)[:, :, 0] > 191)  # more than halfway from the fill to white
    xs, ys = [p[0] for p in corners], [p[1] for p in corners]
    assert np.allclose([cols.min(), rows.min(), cols.max() + 1, rows.max() + 1],
                       [min(xs), min(ys), max(xs), max(ys)], atol=1.5)
    if degrees % 90:
        assert turned.getpixel((0, 0)) == transforms.FILL == turned.getpixel((turned.width - 1, turned.height - 1))
    else:
        assert np.array_equal(np.asarray(turned), np.asarray(image.rotate(degrees, expand=True)))  # exact


def test_srgb_round_trip_is_exact_in_8_bits():
    v = np.arange(256) / 255
    assert np.array_equal(np.round(transforms.linear_to_srgb(transforms.srgb_to_linear(v)) * 255), np.arange(256))


@pytest.mark.parametrize('ev', [1, 2, 3, 4])
def test_darken_scales_linear_light_and_adds_the_stated_noise(ev):
    grey = Image.new('RGB', (256, 256), (128, 128, 128))
    out = transforms.apply(grey, f'dark{ev}', 'some-image')
    linear = transforms.srgb_to_linear(np.asarray(out, dtype=np.float64) / 255)
    x = float(transforms.srgb_to_linear(np.array(128 / 255))) * 2.0 ** -ev
    assert linear.mean() == pytest.approx(x, rel=0.01)
    # Within 0.7% at every level (the seed is fixed); read noise is 7% of the variance at 4 EV, rounding adds 0.3%.
    assert linear.var() == pytest.approx(transforms.LAMBDA_READ + transforms.LAMBDA_SHOT * x, rel=0.02)


def test_darken_is_the_same_every_time_and_differs_between_images():
    photo = Image.fromarray(np.random.default_rng(1).integers(0, 256, (40, 60, 3), dtype=np.uint8), 'RGB')
    first = transforms.png(transforms.apply(photo, 'dark2', 'a'))
    assert transforms.png(transforms.apply(photo, 'dark2', 'a')) == first
    assert transforms.png(transforms.apply(photo, 'dark2', 'b')) != first
    assert transforms.png(transforms.apply(photo, 'dark3', 'a')) != first
    assert transforms.apply(photo, 'none', 'a') is photo
    assert np.array_equal(np.asarray(transforms.apply(photo, 'rot0', 'a')), np.asarray(photo))


def test_noise_parameters_are_the_middle_of_brooks_et_al():
    assert transforms.LAMBDA_SHOT == pytest.approx(0.0010954, rel=1e-4)
    assert transforms.LAMBDA_READ == pytest.approx(1.168e-6, rel=1e-3)
    assert transforms.parameters()['darkening']['lambdaShot'] == transforms.LAMBDA_SHOT


def test_upright_converts_like_chromium(tmp_path):
    rgb = Image.fromarray(np.random.default_rng(2).integers(0, 256, (30, 50, 3), dtype=np.uint8), 'RGB')
    srgb = ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
    lab = ImageCms.ImageCmsProfile(ImageCms.createProfile('LAB')).tobytes()
    cases = {
        'plain.jpg': (rgb, {}),
        'srgb.jpg': (rgb, {'icc_profile': srgb}),
        'lab.jpg': (rgb, {'icc_profile': lab}),                   # a profile of another kind: ignored
        'grey.jpg': (rgb.convert('L'), {'icc_profile': srgb}),     # an RGB profile on a greyscale image: applied
    }
    for name, (image, options) in cases.items():
        (tmp_path / name).write_bytes(jpeg(image, **options).getvalue())
        decoded = np.asarray(Image.open(tmp_path / name).convert('RGB')).astype(int)
        out = transforms.upright(tmp_path / name, 0)
        assert out.mode == 'RGB' and out.size == (50, 30)
        assert np.abs(np.asarray(out).astype(int) - decoded).max() <= 1, name
    rgb.convert('CMYK').save(tmp_path / 'cmyk.jpg', 'JPEG')
    with pytest.raises(ValueError, match='CMYK images are not supported'):
        transforms.upright(tmp_path / 'cmyk.jpg', 0)
    turned = transforms.upright(tmp_path / 'plain.jpg', 90)
    assert turned.size == (30, 50)
    assert np.array_equal(np.asarray(turned), np.asarray(Image.open(tmp_path / 'plain.jpg').rotate(90, expand=True)))


XMP_ORIENTATION_6 = (b'<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF '
                     b'xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"><rdf:Description '
                     b'xmlns:tiff="http://ns.adobe.com/tiff/1.0/" tiff:Orientation="6"/></rdf:RDF></x:xmpmeta>')


def orientation_files(folder):
    """A 40 x 30 photo with no orientation tag, with EXIF orientation 1 and 6, and with XMP orientation 6."""
    image, files = Image.new('RGB', (40, 30), (10, 20, 30)), {}
    for name, orientation, options in (('plain', None, {}), ('one', 1, {}), ('six', 6, {}),
                                       ('xmp', None, {'xmp': XMP_ORIENTATION_6})):
        if orientation:
            exif = Image.Exif()
            exif[0x0112] = orientation
            options['exif'] = exif.tobytes()
        files[name] = folder / f'{name}.jpg'
        files[name].write_bytes(jpeg(image, **options).getvalue())
    return files


def test_upright_refuses_a_file_with_an_exif_orientation(tmp_path):
    files = orientation_files(tmp_path)
    assert [transforms.exif_orientation(path) for path in files.values()] == [None, 1, 6, None]
    assert Image.open(files['xmp']).getexif()[0x0112] == 6  # Pillow's getexif() reads XMP too
    for name in ('plain', 'one', 'xmp'):
        assert transforms.upright(files[name], 90).size == (30, 40)
    with pytest.raises(ValueError, match='EXIF orientation is 6'):
        transforms.upright(files['six'], 0)


def test_chromium_turns_an_image_by_its_exif_orientation_only(chromium, tmp_path):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        for name, path in orientation_files(tmp_path).items():
            size = page.evaluate("""async (data) => {
                const blob = await (await fetch('data:image/jpeg;base64,' + data)).blob();
                const bitmap = await createImageBitmap(blob);
                return [bitmap.width, bitmap.height];
            }""", base64.b64encode(path.read_bytes()).decode())
            assert size == ([30, 40] if transforms.exif_orientation(path) == 6 else [40, 30]), name
        browser.close()


def test_check_colour_agrees_with_chromium_on_each_kind_of_profile(chromium, tmp_path, capsys):
    rgb = Image.fromarray(np.random.default_rng(3).integers(0, 256, (24, 40, 3), dtype=np.uint8), 'RGB')
    srgb = ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
    lab = ImageCms.ImageCmsProfile(ImageCms.createProfile('LAB')).tobytes()
    (tmp_path / 'images').mkdir()
    rows = []
    for name, image, options, rotation in (('plain', rgb, {}, 0), ('srgb', rgb, {'icc_profile': srgb}, 0),
                                           ('lab', rgb, {'icc_profile': lab}, 0),
                                           ('grey', rgb.convert('L'), {'icc_profile': srgb}, 0),
                                           ('turned', rgb, {}, 90)):
        (tmp_path / 'images' / f'{name}.jpg').write_bytes(jpeg(image, **options).getvalue())
        rows.append({'imageId': name, 'url': f'https://example.org/{name}.jpg', 'rotation': rotation})
    (tmp_path / 'manifest').mkdir()
    bm.write_csv(tmp_path / 'manifest/images.csv', ['imageId', 'url', 'rotation'], rows)
    check_colour.main(['--manifest', str(tmp_path / 'manifest'), '--images', str(tmp_path / 'images')])
    out = capsys.readouterr().out
    assert '5 images of 4 kinds' in out and 'sRGB built-in (L, profile RGB)' in out
