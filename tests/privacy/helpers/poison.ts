// Writes a copy of a test photo that carries every kind of hidden data a camera, phone or editor
// can leave in a JPEG, each item marked with a canary, so the suite can show that none of it
// reaches the saved copy. The copy is made at test time from the downloaded photo, never committed.
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import jpeg from 'jpeg-js';
import { FIXTURE_DATA } from '../../env.ts';
import { type Face, type Photo, readFaces, readPhotos } from '../../fixtures/fetch.ts';
import { ascii, bytes, exifTiff, rationals, short, undefinedBytes } from './exif.ts';
import { appIdentifier, parseJpeg, type Segment, segment } from './jpeg.ts';

/** Named like a phone photo, so a test can check the saved copy does not reuse the name. */
export const POISONED_NAME = 'IMG_20261027_143015.jpg';
const TAKEN = '2026:10:27 14:30:15';
const CANARY = 'SOLIDMASK-CANARY';

export type PoisonedPhoto = {
  imageId: string;
  /** The poisoned copy. */
  path: string;
  /** The downloaded photo it was made from. */
  sourcePath: string;
  width: number;
  height: number;
  faces: Face[];
  /** Text planted in the poisoned copy. None of it may appear in a saved copy. */
  planted: string[];
  /** Base64 samples of the photo's compressed image data: a copy encoded afresh contains none of them. */
  scanSamples: string[];
  /** Base64 samples of the hidden preview planted in the EXIF data and after the end of the file. */
  previewSamples: string[];
};

const text = (s: string): Uint8Array => new TextEncoder().encode(s);
const u16 = (n: number): Uint8Array => new Uint8Array([n >> 8, n & 0xff]);
const u32 = (n: number): Uint8Array => new Uint8Array([n >>> 24, (n >> 16) & 0xff, (n >> 8) & 0xff, n & 0xff]);

function concat(...parts: Uint8Array[]): Uint8Array {
  const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0));
  let at = 0;
  for (const p of parts) {
    out.set(p, at);
    at += p.length;
  }
  return out;
}

/** A small JPEG of the whole photo, face included: the "hidden preview" the README promises to drop. */
function preview(source: Uint8Array): Uint8Array {
  const image = jpeg.decode(source, { useTArray: true, formatAsRGBA: true, maxMemoryUsageInMB: 1024 });
  const scale = Math.max(image.width, image.height) / 160;
  const w = Math.round(image.width / scale);
  const h = Math.round(image.height / scale);
  const out = new Uint8Array(4 * w * h);
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const [x0, x1] = [Math.floor(x * scale), Math.min(image.width, Math.floor((x + 1) * scale))];
      const [y0, y1] = [Math.floor(y * scale), Math.min(image.height, Math.floor((y + 1) * scale))];
      const sum = [0, 0, 0];
      for (let sy = y0; sy < y1; sy++) {
        for (let sx = x0; sx < x1; sx++) {
          const i = 4 * (sy * image.width + sx);
          sum[0] += image.data[i];
          sum[1] += image.data[i + 1];
          sum[2] += image.data[i + 2];
        }
      }
      const n = (x1 - x0) * (y1 - y0);
      out.set([sum[0] / n, sum[1] / n, sum[2] / n, 255], 4 * (y * w + x));
    }
  }
  return new Uint8Array(jpeg.encode({ data: out, width: w, height: h }, 80).data);
}

function exifSegment(thumbnail: Uint8Array): Uint8Array {
  const tiff = exifTiff(
    [
      ascii(0x010e, `${CANARY}-EXIF-DESCRIPTION`),
      ascii(0x010f, `${CANARY}-MAKE`),
      ascii(0x0110, `${CANARY}-MODEL`),
      short(0x0112, 1), // orientation: upright, so the face boxes stay valid
      ascii(0x0131, `${CANARY}-SOFTWARE`),
      ascii(0x0132, TAKEN),
      ascii(0x013b, `${CANARY}-ARTIST`),
    ],
    [
      ascii(0x9003, TAKEN),
      undefinedBytes(0x927c, text(`${CANARY}-MAKERNOTE`)),
      ascii(0xa431, `${CANARY}-SERIAL`),
      ascii(0xa434, `${CANARY}-LENS`),
    ],
    [
      // A made-up position at sea, never a real one (CLAUDE.md, rule 3).
      bytes(0x0000, new Uint8Array([2, 3, 0, 0])),
      ascii(0x0001, 'N'),
      rationals(0x0002, [[12, 1], [34, 1], [5678, 100]]),
      ascii(0x0003, 'E'),
      rationals(0x0004, [[98, 1], [7, 1], [5432, 100]]),
      undefinedBytes(0x001c, text(`ASCII\0\0\0${CANARY}-GPS`)),
    ],
    thumbnail,
  );
  return segment(0xe1, concat(text('Exif\0\0'), tiff));
}

function xmpSegment(): Uint8Array {
  const packet =
    '<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>' +
    '<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">' +
    '<rdf:Description rdf:about="" xmlns:dc="http://purl.org/dc/elements/1.1/" ' +
    'xmlns:photoshop="http://ns.adobe.com/photoshop/1.0/" xmlns:exif="http://ns.adobe.com/exif/1.0/">' +
    `<dc:description><rdf:Alt><rdf:li xml:lang="x-default">${CANARY}-XMP-DESCRIPTION</rdf:li></rdf:Alt></dc:description>` +
    `<photoshop:City>${CANARY}-XMP-CITY</photoshop:City>` +
    '<exif:GPSLatitude>12,34.9463N</exif:GPSLatitude><exif:GPSLongitude>98,7.9053E</exif:GPSLongitude>' +
    '</rdf:Description></rdf:RDF></x:xmpmeta><?xpacket end="w"?>';
  return segment(0xe1, concat(text('http://ns.adobe.com/xap/1.0/\0'), text(packet)));
}

/** IPTC-NAA records inside a Photoshop image resource block, as Photoshop and many phones write them. */
function iptcSegment(): Uint8Array {
  const record = (dataset: number, value: string): Uint8Array => concat(new Uint8Array([0x1c, 2, dataset]), u16(value.length), text(value));
  const iptc = concat(record(0x78, `${CANARY}-IPTC-CAPTION`), record(0x5a, `${CANARY}-IPTC-CITY`), record(0x50, `${CANARY}-IPTC-BYLINE`));
  const resource = concat(text('8BIM'), u16(0x0404), new Uint8Array([0, 0]), u32(iptc.length), iptc, new Uint8Array(iptc.length % 2));
  return segment(0xed, concat(text('Photoshop 3.0\0'), resource));
}

/** A C2PA manifest store in a JUMBF box, carried in APP11 as JPEG XT specifies. */
function c2paSegment(): Uint8Array {
  const box = (type: string, ...content: Uint8Array[]): Uint8Array => {
    const body = concat(...content);
    return concat(u32(8 + body.length), text(type), body);
  };
  const c2paUuid = new Uint8Array([0x63, 0x32, 0x70, 0x61, 0x00, 0x11, 0x00, 0x10, 0x80, 0x00, 0x00, 0xaa, 0x00, 0x38, 0x9b, 0x71]);
  const store = box(
    'jumb',
    box('jumd', c2paUuid, new Uint8Array([0x03]), text('c2pa\0')),
    box('json', text(JSON.stringify({ canary: `${CANARY}-C2PA` }))),
  );
  return segment(0xeb, concat(text('JP'), u16(1), u32(1), store));
}

/** Evenly spaced windows of `size` bytes with varied content, base64-encoded. */
function samples(data: Uint8Array, count: number, size: number): string[] {
  const out: string[] = [];
  const step = Math.max(1, Math.floor((data.length - size) / (2 * count)));
  for (let at = 0; at + size <= data.length && out.length < count; at += step) {
    const window = data.subarray(at, at + size);
    if (new Set(window).size >= size / 2) out.push(Buffer.from(window).toString('base64'));
  }
  return out;
}

const isMetadata = (s: Segment): boolean => (s.marker >= 0xe0 && s.marker <= 0xef) || s.marker === 0xfe;
// Kept from the original: they change how the picture decodes, and a saved copy must still not carry them.
const isKeptApp = (s: Segment): boolean =>
  (s.marker === 0xe2 && appIdentifier(s) === 'ICC_PROFILE') || (s.marker === 0xee && appIdentifier(s) === 'Adobe');

const sidecar = (imageId: string): string => join(FIXTURE_DATA, 'poisoned', `${imageId}.json`);
const poisonedPath = (imageId: string): string => join(FIXTURE_DATA, 'poisoned', imageId, POISONED_NAME);

export async function writePoisonedPhoto(photo: Photo): Promise<void> {
  const source = new Uint8Array(await readFile(photo.path));
  const parsed = parseJpeg(source);
  const thumbnail = preview(source);

  const kept: Uint8Array[] = [];
  const keptIdentifiers: string[] = [];
  const picture: Uint8Array[] = [];
  let scan = 0;
  for (const s of parsed.segments) {
    const whole = source.subarray(s.offset, s.offset + 4 + s.payload.length);
    if (isKeptApp(s)) {
      kept.push(whole);
      keptIdentifiers.push(appIdentifier(s));
    }
    if (isMetadata(s)) continue;
    picture.push(whole);
    if (s.marker === 0xda) {
      const { start, end } = parsed.scans[scan++];
      picture.push(source.subarray(start, end));
    }
  }

  const poisoned = concat(
    new Uint8Array([0xff, 0xd8]),
    exifSegment(thumbnail),
    xmpSegment(),
    ...kept,
    c2paSegment(),
    iptcSegment(),
    segment(0xfe, text(`${CANARY}-COMMENT`)),
    ...picture,
    new Uint8Array([0xff, 0xd9]),
    // Leftover data after the end of the image, as aCropalypse left it, followed by a second picture.
    text(`${CANARY}-TRAILER`),
    thumbnail,
  );

  const firstScan = parsed.scans[0];
  const previewScan = parseJpeg(thumbnail).scans[0];
  const details = {
    planted: [CANARY, TAKEN, 'Exif\0\0', 'http://ns.adobe.com/', 'Photoshop 3.0', '8BIM', 'jumb', 'c2pa', ...keptIdentifiers],
    scanSamples: samples(source.subarray(firstScan.start, firstScan.end), 64, 32),
    previewSamples: samples(thumbnail.subarray(previewScan.start, previewScan.end), 8, 16),
  };
  await mkdir(join(FIXTURE_DATA, 'poisoned', photo.imageId), { recursive: true });
  await writeFile(poisonedPath(photo.imageId), poisoned);
  await writeFile(sidecar(photo.imageId), JSON.stringify(details, null, 2));
}

/** The poisoned copy of the first photo in the manifest, with what was planted in it. */
export async function poisonedPhoto(): Promise<PoisonedPhoto> {
  const [photo] = await readPhotos();
  const details = JSON.parse(await readFile(sidecar(photo.imageId), 'utf8'));
  return {
    imageId: photo.imageId,
    path: poisonedPath(photo.imageId),
    sourcePath: photo.path,
    width: photo.width,
    height: photo.height,
    faces: await readFaces(photo.imageId),
    ...details,
  };
}

const asBuffer = (b: Uint8Array): Buffer => Buffer.from(b.buffer, b.byteOffset, b.length);

/** Which of `needles` (byte strings) occur in `haystack`. */
export function found(haystack: Uint8Array, needles: string[]): string[] {
  const h = asBuffer(haystack);
  return needles.filter((n) => h.includes(Buffer.from(n, 'latin1')));
}

/** How many of the base64 `samples` occur in `haystack`. */
export function samplesFound(haystack: Uint8Array, samples64: string[]): number {
  const h = asBuffer(haystack);
  return samples64.filter((s) => h.includes(Buffer.from(s, 'base64'))).length;
}
