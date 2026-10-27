/** JPEG quality of the saved copy (docs/contracts.md, section 2). */
export const JPEG_QUALITY = 0.92;

// Written in place of whatever header the browser wrote: JFIF 1.01, no units, 1:1 pixel aspect
// ratio, no thumbnail.
const JFIF = [0xff, 0xe0, 0x00, 0x10, 0x4a, 0x46, 0x49, 0x46, 0x00, 0x01, 0x01, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00, 0x00];

// What a decoder needs: frame headers (baseline, extended, progressive), Huffman and quantisation
// tables, the restart interval, and scans.
const CODING = new Set([0xc0, 0xc1, 0xc2, 0xc4, 0xdb, 0xdd, 0xda]);

const isRestart = (marker: number): boolean => marker >= 0xd0 && marker <= 0xd7;

/**
 * Rebuilds a JPEG from the picture alone: start of image, a plain JFIF header, the coding segments
 * and scans, end of image. Every APPn segment (EXIF, XMP, ICC, IPTC, MPF, C2PA and the rest), every
 * comment, and every byte after the end of the image is left out. Anything it does not recognise
 * is an error, so a file it cannot vouch for is never saved.
 */
export function stripJpeg(bytes: Uint8Array): Uint8Array<ArrayBuffer> {
  if (bytes[0] !== 0xff || bytes[1] !== 0xd8) throw new Error('not a JPEG');
  const parts: Uint8Array[] = [Uint8Array.of(0xff, 0xd8), Uint8Array.from(JFIF)];
  let pos = 2;
  for (;;) {
    if (pos + 1 >= bytes.length || bytes[pos] !== 0xff) throw new Error(`no marker at byte ${pos}`);
    const marker = bytes[pos + 1];
    if (marker === 0xff) {
      pos++; // fill byte
      continue;
    }
    if (marker === 0xd9) {
      parts.push(Uint8Array.of(0xff, 0xd9));
      break;
    }
    if (pos + 3 >= bytes.length) throw new Error(`segment at byte ${pos} is cut short`);
    const end = pos + 2 + ((bytes[pos + 2] << 8) | bytes[pos + 3]);
    if (end > bytes.length) throw new Error(`segment at byte ${pos} runs past the end`);
    const metadata = (marker >= 0xe0 && marker <= 0xef) || marker === 0xfe;
    if (!metadata) {
      if (!CODING.has(marker)) throw new Error(`unexpected marker FF${marker.toString(16).toUpperCase()} at byte ${pos}`);
      parts.push(bytes.subarray(pos, end));
    }
    pos = end;
    if (marker === 0xda) {
      // Entropy-coded data runs to the next marker that is neither a stuffed FF 00 nor a restart marker.
      const start = pos;
      while (pos + 1 < bytes.length && !(bytes[pos] === 0xff && bytes[pos + 1] !== 0x00 && !isRestart(bytes[pos + 1]))) pos++;
      parts.push(bytes.subarray(start, pos));
    }
  }
  const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0));
  let at = 0;
  for (const p of parts) {
    out.set(p, at);
    at += p.length;
  }
  return out;
}

/**
 * Encodes the canvas afresh as a JPEG at quality 0.92, then keeps only the picture: the browser's
 * encoder may add segments of its own (Safari's writes through Apple's ImageIO).
 */
export async function encodeJpeg(canvas: HTMLCanvasElement): Promise<Blob> {
  const encoded = await new Promise<Blob>((resolve, reject) =>
    canvas.toBlob((blob) => (blob ? resolve(blob) : reject(new Error('the browser could not encode the photo'))), 'image/jpeg', JPEG_QUALITY),
  );
  return new Blob([stripJpeg(new Uint8Array(await encoded.arrayBuffer()))], { type: 'image/jpeg' });
}
