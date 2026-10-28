"""PDQ, Meta's 256-bit perceptual hash, for check E3 of docs/eval-protocol.md, part E.

Written in numpy from the algorithm of Meta's reference implementation (facebook/ThreatExchange, pdq/cpp: hashing/
pdqhashing.cpp and downscaling/downscaling.cpp, BSD licence), without its code. It repeats the reference's float32
arithmetic step for step, so that the same pixels give the same hash:

1. luma Y = 0.299 R + 0.587 G + 0.114 B;
2. two passes of a box filter along each row, then along each column, with a window of (n + 127) // 128 pixels for
   a side of n pixels, computed as a running sum;
3. the 64 x 64 samples at the centres of a 64 x 64 grid;
4. the 16 x 16 DCT of those samples, leaving out the constant (DC) row and column;
5. one bit per coefficient, set when the coefficient is above the 128th smallest of the 256.

The quality is the sum of the 64 x 64 samples' gradients, each scaled to 0..100 of the luma range and truncated,
divided by 90 and capped at 100. Meta recommends treating hashes within distance 31 as matching and discarding hashes
of quality 49 or less. hash_image() first shrinks an image to at most 512 pixels on a side, keeping its shape, as
Meta's Python reference does (Image.thumbnail).
"""
import math
import numpy as np
from PIL import Image

LUMA = (np.float32(0.299), np.float32(0.587), np.float32(0.114))
MATCH_DISTANCE = 31
MIN_QUALITY = 50
_SCALE = np.float32(math.sqrt(2.0 / 64))
DCT = np.array([[np.float32(float(_SCALE) * math.cos((math.pi / 2.0 / 64) * (i + 1) * (2 * j + 1)))
                 for j in range(64)] for i in range(16)], dtype=np.float32)


def luma(rgb):
    """float32 luma of an h x w x 3 uint8 array, in the reference's order of operations."""
    r, g, b = (rgb[:, :, c].astype(np.float32) for c in range(3))
    return LUMA[0] * r + LUMA[1] * g + LUMA[2] * b


def window(side):
    return (side + 2 * 64 - 1) // (2 * 64)


def box(values, size):
    """The reference's running-sum box filter along axis 0 of a float32 array, for every column at once. Output k is
    the mean of inputs k - (size - half) to k + half - 1, as far as they exist, where half = (size + 2) // 2."""
    n = values.shape[0]
    half = (size + 2) // 2
    out = np.empty_like(values)
    total = np.zeros(values.shape[1:], dtype=np.float32)
    left = right = at = count = 0
    for _ in range(half - 1):                      # fill the first half window, no output yet
        total = total + values[right]
        count, right = count + 1, right + 1
    for _ in range(size - half + 1):               # grow to the full window
        total = total + values[right]
        count, right = count + 1, right + 1
        out[at] = total / np.float32(count)
        at += 1
    for _ in range(n - size):                      # slide the full window
        total = total + values[right]
        total = total - values[left]
        out[at] = total / np.float32(count)
        left, right, at = left + 1, right + 1, at + 1
    for _ in range(half - 1):                      # shrink at the end
        total = total - values[left]
        count, left = count - 1, left + 1
        out[at] = total / np.float32(count)
        at += 1
    return out


def downsample(values):
    """The 64 x 64 samples of a luma array: blurred twice along rows and columns, then taken at cell centres."""
    rows, cols = values.shape
    for _ in range(2):
        values = box(values.T, window(cols)).T     # along each row
        values = box(values, window(rows))         # along each column
    i = [int(((k + 0.5) * rows) / 64) for k in range(64)]
    j = [int(((k + 0.5) * cols) / 64) for k in range(64)]
    return values[np.ix_(i, j)]


def quality(samples):
    """The reference's quality metric, 0 to 100, from the 64 x 64 samples."""
    down = np.trunc(((samples[:-1, :] - samples[1:, :]) * np.float32(100)) / np.float32(255))
    across = np.trunc(((samples[:, :-1] - samples[:, 1:]) * np.float32(100)) / np.float32(255))
    return min(100, int(np.abs(down).sum() + np.abs(across).sum()) // 90)


def dct16(samples):
    """DCT x samples x DCT^T, each sum taken in order in float32, as the reference does."""
    partial = np.zeros((16, 64), dtype=np.float32)
    for k in range(64):
        partial = partial + DCT[:, k, None] * samples[k, None, :]
    out = np.zeros((16, 16), dtype=np.float32)
    for k in range(64):
        out = out + partial[:, k, None] * DCT[None, :, k]
    return out


def hash_luma(values):
    """(hash as 64 hex digits, quality) of a float32 luma array of at least 5 x 5 pixels."""
    if min(values.shape) < 5:
        raise ValueError('PDQ needs an image of at least 5 x 5 pixels')
    samples = downsample(np.asarray(values, dtype=np.float32))
    coefficients = dct16(samples)
    median = np.partition(coefficients.ravel(), 127)[127]   # the 128th smallest
    bits = coefficients > median
    words = [int(np.dot(bits[i].astype(np.int64), 1 << np.arange(16))) for i in range(16)]
    return ''.join(f'{w:04x}' for w in reversed(words)), quality(samples)


def hash_image(image):
    """(hash, quality) of a PIL image, shrunk to at most 512 x 512 pixels keeping its shape, as Meta's Python
    reference does."""
    image = image.convert('RGB')
    image.thumbnail((512, 512))
    return hash_luma(luma(np.asarray(image)))


def distance(a, b):
    """Hamming distance between two hashes given as hex strings."""
    return (int(a, 16) ^ int(b, 16)).bit_count()
