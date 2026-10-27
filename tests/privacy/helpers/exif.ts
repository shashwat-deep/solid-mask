// Just enough of a TIFF writer to plant EXIF test data: little-endian ("II"), no compression.

export type Field = { tag: number; type: number; count: number; value: Uint8Array };

const BYTE = 1;
const ASCII = 2;
const SHORT = 3;
const LONG = 4;
const RATIONAL = 5;
const UNDEFINED = 7;

function littleEndian(size: number, write: (view: DataView) => void): Uint8Array {
  const out = new Uint8Array(size);
  write(new DataView(out.buffer));
  return out;
}

export const ascii = (tag: number, text: string): Field => {
  const value = new TextEncoder().encode(`${text}\0`);
  return { tag, type: ASCII, count: value.length, value };
};
export const bytes = (tag: number, value: Uint8Array): Field => ({ tag, type: BYTE, count: value.length, value });
export const undefinedBytes = (tag: number, value: Uint8Array): Field => ({ tag, type: UNDEFINED, count: value.length, value });
export const short = (tag: number, n: number): Field => ({ tag, type: SHORT, count: 1, value: littleEndian(2, (v) => v.setUint16(0, n, true)) });
export const long = (tag: number, n: number): Field => ({ tag, type: LONG, count: 1, value: littleEndian(4, (v) => v.setUint32(0, n, true)) });
export const rationals = (tag: number, pairs: [number, number][]): Field => ({
  tag,
  type: RATIONAL,
  count: pairs.length,
  value: littleEndian(8 * pairs.length, (v) =>
    pairs.forEach(([num, den], i) => {
      v.setUint32(8 * i, num, true);
      v.setUint32(8 * i + 4, den, true);
    }),
  ),
});

const even = (n: number): number => n + (n & 1);

/** Bytes an IFD takes: entry count, 12-byte entries, next-IFD pointer, then values too long to fit in an entry. */
function ifdLength(fields: Field[]): number {
  return 2 + 12 * fields.length + 4 + fields.reduce((n, f) => n + (f.value.length > 4 ? even(f.value.length) : 0), 0);
}

function writeIfd(out: Uint8Array, start: number, fields: Field[], next: number): void {
  const view = new DataView(out.buffer, out.byteOffset);
  const sorted = [...fields].sort((a, b) => a.tag - b.tag);
  view.setUint16(start, sorted.length, true);
  let data = start + 2 + 12 * sorted.length + 4;
  sorted.forEach((f, i) => {
    const entry = start + 2 + 12 * i;
    view.setUint16(entry, f.tag, true);
    view.setUint16(entry + 2, f.type, true);
    view.setUint32(entry + 4, f.count, true);
    if (f.value.length <= 4) {
      out.set(f.value, entry + 8);
    } else {
      view.setUint32(entry + 8, data, true);
      out.set(f.value, data);
      data += even(f.value.length);
    }
  });
  view.setUint32(start + 2 + 12 * sorted.length, next, true);
}

/**
 * A TIFF structure as EXIF uses it: IFD0 points to an Exif IFD and a GPS IFD, and IFD1 holds a
 * JPEG thumbnail. Offsets count from the start of the TIFF header.
 */
export function exifTiff(ifd0: Field[], exif: Field[], gps: Field[], thumbnail: Uint8Array): Uint8Array {
  // Pointer fields are 4-byte values, so laying out with zeros first gives the final sizes.
  const ifd1 = [short(0x0103, 6), long(0x0201, 0), long(0x0202, thumbnail.length)];
  const at0 = 8;
  const atExif = at0 + ifdLength([...ifd0, long(0x8769, 0), long(0x8825, 0)]);
  const atGps = atExif + ifdLength(exif);
  const at1 = atGps + ifdLength(gps);
  const atThumbnail = at1 + ifdLength(ifd1);
  ifd1[1] = long(0x0201, atThumbnail);

  const out = new Uint8Array(atThumbnail + thumbnail.length);
  out.set([0x49, 0x49, 0x2a, 0x00, at0, 0, 0, 0]);
  writeIfd(out, at0, [...ifd0, long(0x8769, atExif), long(0x8825, atGps)], at1);
  writeIfd(out, atExif, exif, 0);
  writeIfd(out, atGps, gps, 0);
  writeIfd(out, at1, ifd1, 0);
  out.set(thumbnail, atThumbnail);
  return out;
}
