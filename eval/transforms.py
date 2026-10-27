"""The image transforms of docs/eval-protocol.md, part B: rotation (rot<degrees>) and darkening (dark<EV>).

So far this file holds the geometry that score.py needs: the size of a rotated image, and where a point of the
upright image lands in it. A rotation is Pillow's Image.rotate(degrees, expand=True): counterclockwise about the
image's centre, on a canvas enlarged to fit. The functions below repeat Pillow's arithmetic, including its exact
transposes for 90, 180 and 270 degrees, so the rotated images and the rotated face boxes line up; the tests check
this against Pillow. Darkening leaves the geometry unchanged. The code that makes the transformed images, and the
noise parameters for darkening, come with the runner, before the first run.
"""
import math, re


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
