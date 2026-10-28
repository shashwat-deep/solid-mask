"""The image transforms of docs/eval-protocol.md, part B: rotation (rot<degrees>) and darkening (dark<EV>).

run_detect.py makes each transformed image when the page asks for it, so none is stored. It starts from the image
as the browser shows it: the stored JPEG converted to sRGB by its ICC profile, if it has one, and turned upright by
Open Images' Rotation (upright()). Then:

- rot<degrees> turns it counterclockwise by that many degrees with Pillow's Image.rotate: bicubic resampling, on a
  canvas enlarged to fit, with the uncovered corners in mid-grey (FILL). 90, 180 and 270 degrees are exact
  transposes. rotated_size() and rotate_points() repeat Pillow's arithmetic, so the rotated images and the rotated
  face boxes that score.py uses line up; the tests check this against Pillow.
- dark<EV> converts it to linear RGB (IEC 61966-2-1), multiplies by 2^-EV, adds sensor noise and converts it back
  to 8-bit sRGB. The noise is Poisson-Gaussian: for a linear value x, a Poisson count with mean x / LAMBDA_SHOT,
  times LAMBDA_SHOT, plus Gaussian noise with variance LAMBDA_READ, so the variance is LAMBDA_READ + LAMBDA_SHOT x,
  the model of Brooks et al., "Unprocessing images for learned raw denoising", CVPR 2019, Eq. 1. They fit
  log LAMBDA_SHOT to the uniform distribution on [log 0.0001, log 0.012] and log LAMBDA_READ to
  2.18 log LAMBDA_SHOT + 1.2 on the Darmstadt Noise Dataset (Eq. 3); the values below are the middle of that range
  and the fitted line. Each image and level has its own random generator, seeded from its ID and the transform.
"""
import hashlib, io, math, re
import numpy as np
from PIL import Image, ImageCms

FILL = (128, 128, 128)
RESAMPLE = Image.Resampling.BICUBIC
LAMBDA_SHOT = math.sqrt(0.0001 * 0.012)                      # about 0.0011
LAMBDA_READ = math.exp(2.18 * math.log(LAMBDA_SHOT) + 1.2)   # about 1.17e-6
SRGB = ImageCms.createProfile('sRGB')


def parse(transform):
    """'none', 'rot<degrees>' or 'dark<EV>' -> ('none', 0.0), ('rot', degrees) or ('dark', EV)."""
    if transform == 'none':
        return 'none', 0.0
    match = re.fullmatch(r'(rot|dark)(\d+(?:\.\d+)?)', transform)
    if not match:
        raise ValueError(f'unknown transform {transform!r}: expected none, rot<degrees> or dark<EV>')
    return match[1], float(match[2])


def _pillow_matrix(width, height, degrees):
    """Pillow's affine matrix (a, b, c, d, e, f) from the rotated canvas to the upright image, and the canvas size,
    for an angle that Pillow does not handle as a transpose."""
    angle = -math.radians(degrees)
    a, b = round(math.cos(angle), 15), round(math.sin(angle), 15)
    d, e = -b, a
    cx, cy = width / 2, height / 2
    c, f = a * -cx + b * -cy + cx, d * -cx + e * -cy + cy
    xs = [a * x + b * y + c for x, y in ((0, 0), (width, 0), (width, height), (0, height))]
    ys = [d * x + e * y + f for x, y in ((0, 0), (width, 0), (width, height), (0, height))]
    new_w = math.ceil(max(xs)) - math.floor(min(xs))
    new_h = math.ceil(max(ys)) - math.floor(min(ys))
    dx, dy = -(new_w - width) / 2, -(new_h - height) / 2
    return (a, b, a * dx + b * dy + c, d, e, d * dx + e * dy + f), (new_w, new_h)


def rotated_size(width, height, degrees):
    """(width, height) of the image rotated counterclockwise by degrees on a canvas enlarged to fit."""
    degrees %= 360
    if degrees in (0, 180):
        return width, height
    if degrees in (90, 270):
        return height, width
    return _pillow_matrix(width, height, degrees)[1]


def rotate_points(points, width, height, degrees):
    """Where the points (x, y) of the upright width × height image land once it is rotated counterclockwise by
    degrees on a canvas enlarged to fit. Coordinates are continuous: pixel (i, j) covers [i, i + 1) × [j, j + 1)."""
    degrees %= 360
    if degrees == 0:
        return [(x, y) for x, y in points]
    if degrees == 90:
        return [(y, width - x) for x, y in points]
    if degrees == 180:
        return [(width - x, height - y) for x, y in points]
    if degrees == 270:
        return [(height - y, x) for x, y in points]
    (a, b, c, d, e, f), _ = _pillow_matrix(width, height, degrees)
    det = a * e - b * d  # Pillow maps canvas -> image; invert it to map image -> canvas
    return [((e * (x - c) - b * (y - f)) / det, (a * (y - f) - d * (x - c)) / det) for x, y in points]


def srgb_to_linear(v):
    """sRGB values in [0, 1] -> linear light (IEC 61966-2-1)."""
    return np.where(v <= 0.04045, v / 12.92, ((v + 0.055) / 1.055) ** 2.4)


def linear_to_srgb(v):
    """Linear light in [0, 1] -> sRGB values (IEC 61966-2-1)."""
    return np.where(v <= 0.0031308, v * 12.92, 1.055 * np.power(v, 1 / 2.4) - 0.055)


# darken() works through these two tables rather than calling the formulas for each pixel: each 8-bit value's linear
# light, and the linear values at which the 8-bit sRGB value steps up (halfway between two values). An output
# pixel then depends on comparisons with fixed numbers only, which keeps reruns identical.
TO_LINEAR = srgb_to_linear(np.arange(256) / 255)
STEPS = srgb_to_linear((np.arange(1, 256) - 0.5) / 255)


def exif_orientation(path):
    """The Orientation tag in an image file's EXIF data, which Chromium applies, or None when there is none.
    (Pillow's getexif() would also report XMP's tiff:Orientation, which Chromium ignores.)"""
    with Image.open(path) as image:
        exif = Image.Exif()
        if image.info.get('exif'):
            exif.load(image.info['exif'])
        return exif.get(0x0112)


def upright(path, rotation):
    """The stored image as Chromium shows it: converted to sRGB by its ICC profile (relative colorimetric
    intent), as RGB, and turned counterclockwise by Open Images' Rotation. Like Chromium, it applies an RGB profile
    to a greyscale image as if the image were RGB (14 greyscale test images carry one), and ignores a profile of
    another kind (one RGB test image carries a CMYK profile). On test images of each kind, the result is within 1
    of Chromium's decoded pixels. Images in other modes (CMYK, for example) have not been compared, so they are
    refused, and so is a file with an EXIF orientation other than 1, which Chromium would apply (build_manifest.py
    leaves such images out)."""
    orientation = exif_orientation(path)
    if orientation not in (None, 1):
        raise ValueError(f'{path}: its EXIF orientation is {orientation}, not 1')
    with Image.open(path) as image:
        if image.mode not in ('RGB', 'L'):
            raise ValueError(f'{path}: {image.mode} images are not supported; check them with check_colour.py first')
        icc = image.info.get('icc_profile')
        if icc:
            profile = ImageCms.ImageCmsProfile(io.BytesIO(icc))
            space = profile.profile.xcolor_space.strip()
            if image.mode == 'L' and space == 'RGB':
                image = image.convert('RGB')
            if space == {'RGB': 'RGB', 'L': 'GRAY'}.get(image.mode):
                image = ImageCms.profileToProfile(image, profile, SRGB, outputMode='RGB',
                                                  renderingIntent=ImageCms.Intent.RELATIVE_COLORIMETRIC)
        image = image.convert('RGB')
    return image.rotate(rotation, expand=True)


def seed(image_id, transform):
    return int(hashlib.sha256(f'solid-mask:{transform}:{image_id}'.encode()).hexdigest()[:16], 16)


def rotate(image, degrees):
    return image.rotate(degrees, resample=RESAMPLE, expand=True, fillcolor=FILL)


def darken(image, ev, rng):
    x = TO_LINEAR[np.asarray(image)] * 2.0 ** -ev
    y = rng.poisson(x / LAMBDA_SHOT) * LAMBDA_SHOT + rng.normal(0.0, math.sqrt(LAMBDA_READ), x.shape)
    return Image.fromarray(np.searchsorted(STEPS, y, side='right').astype(np.uint8), 'RGB')  # clips to [0, 255]


def apply(image, transform, image_id):
    """The upright RGB image under one transform. Deterministic: the same image and transform give the same pixels."""
    kind, value = parse(transform)
    if kind == 'rot':
        return rotate(image, value)
    if kind == 'dark':
        return darken(image, value, np.random.default_rng(seed(image_id, transform)))
    return image


def png(image):
    buffer = io.BytesIO()
    image.save(buffer, 'PNG', compress_level=1)
    return buffer.getvalue()


def parameters():
    """What run_info.json records about the transforms."""
    return {'rotation': {'fill': list(FILL), 'resample': RESAMPLE.name.lower(), 'direction': 'counterclockwise'},
            'darkening': {'lambdaShot': LAMBDA_SHOT, 'lambdaRead': LAMBDA_READ,
                          'seed': 'first 16 hex digits of sha256("solid-mask:<transform>:<imageId>")'},
            'colour': 'ICC profile to sRGB, relative colorimetric, LittleCMS'}
