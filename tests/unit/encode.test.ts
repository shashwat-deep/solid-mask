import { describe, expect, it } from 'vitest';
import { stripJpeg } from '../../app/src/pipeline/encode.ts';

/** A marker segment: FF, marker, 16-bit length, payload. */
function segment(marker: number, payload: number[] | string): number[] {
  const bytes = typeof payload === 'string' ? [...new TextEncoder().encode(payload)] : payload;
  return [0xff, marker, (bytes.length + 2) >> 8, (bytes.length + 2) & 0xff, ...bytes];
}

const SOI = [0xff, 0xd8];
const EOI = [0xff, 0xd9];
const JFIF_PLAIN = segment(0xe0, [0x4a, 0x46, 0x49, 0x46, 0, 1, 1, 0, 0, 1, 0, 1, 0, 0]);
const DQT = segment(0xdb, [0, ...Array(64).fill(1)]);
const SOF0 = segment(0xc0, [8, 0, 16, 0, 16, 3, 1, 0x22, 0, 2, 0x11, 1, 3, 0x11, 1]);
const DHT = segment(0xc4, [0, ...Array(16).fill(0)]);
const DRI = segment(0xdd, [0, 4]);
const SOS = segment(0xda, [3, 1, 0, 2, 0x11, 3, 0x11, 0, 63, 0]);
// Entropy-coded data with a stuffed FF 00 and a restart marker, both of which belong to the scan.
const SCAN = [0x12, 0xff, 0x00, 0x34, 0xff, 0xd0, 0x56];

const strip = (...parts: number[][]): number[] => [...stripJpeg(Uint8Array.from(parts.flat()))];

describe('stripJpeg', () => {
  it('keeps the picture and drops every metadata segment, comment and trailing byte', () => {
    const thumbnailJfif = segment(0xe0, [0x4a, 0x46, 0x49, 0x46, 0, 1, 1, 0, 0, 1, 0, 1, 1, 1, 9, 9, 9]);
    const exif = segment(0xe1, 'Exif\0\0GPS and a thumbnail');
    const icc = segment(0xe2, 'ICC_PROFILE\0...');
    const iptc = segment(0xed, 'Photoshop 3.0\0...');
    const c2pa = segment(0xeb, 'JP...c2pa');
    const comment = segment(0xfe, 'a comment');
    const afterEnd = [...new TextEncoder().encode('leftover data'), ...SOI, ...EOI];
    expect(strip(SOI, thumbnailJfif, exif, icc, iptc, c2pa, comment, DQT, SOF0, DRI, DHT, SOS, SCAN, EOI, afterEnd)).toEqual(
      [SOI, JFIF_PLAIN, DQT, SOF0, DRI, DHT, SOS, SCAN, EOI].flat(),
    );
  });

  it('keeps every scan of a progressive JPEG, with the tables between them', () => {
    const SOF2 = [0xff, 0xc2, ...SOF0.slice(2)];
    expect(strip(SOI, DQT, SOF2, DHT, SOS, SCAN, DHT, SOS, SCAN, EOI)).toEqual([SOI, JFIF_PLAIN, DQT, SOF2, DHT, SOS, SCAN, DHT, SOS, SCAN, EOI].flat());
  });

  it('skips fill bytes before a marker', () => {
    expect(strip(SOI, [0xff], DQT, SOF0, DHT, SOS, SCAN, [0xff], EOI)).toEqual([SOI, JFIF_PLAIN, DQT, SOF0, DHT, SOS, SCAN, EOI].flat());
  });

  it('refuses a file it cannot vouch for', () => {
    expect(() => strip([0x89, 0x50, 0x4e, 0x47])).toThrow('not a JPEG');
    expect(() => strip(SOI, DQT, SOF0, DHT, SOS, SCAN)).toThrow(); // no end of image
    expect(() => strip(SOI, DQT, segment(0xc3, [8, 0, 1, 0, 1, 1, 1, 0x11, 0]), EOI)).toThrow('unexpected marker FFC3'); // lossless
    expect(() => strip(SOI, [0xff, 0xdb, 0x01, 0x00, 0])).toThrow('runs past the end');
  });
});
