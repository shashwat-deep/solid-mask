// Reads the structure of a JPEG file, marker by marker. This is independent of the app's own
// code on purpose: a bug in the app's metadata stripping must not hide itself here.

export type Segment = { marker: number; offset: number; payload: Uint8Array };

export type Frame = {
  width: number;
  height: number;
  components: { id: number; h: number; v: number }[];
  /** Size of one MCU (minimum coded unit) in pixels: 8 times the largest sampling factor. */
  mcuWidth: number;
  mcuHeight: number;
};

export type Jpeg = {
  segments: Segment[];
  /** Entropy-coded data after each start-of-scan segment: [start, end) byte offsets. */
  scans: { start: number; end: number }[];
  frames: Frame[];
  /** Offset of the end-of-image marker (FF D9). */
  eoi: number;
  /** Everything after the end-of-image marker. */
  trailing: Uint8Array;
};

const SOI = 0xd8;
const EOI = 0xd9;
const SOS = 0xda;

const isRst = (m: number): boolean => m >= 0xd0 && m <= 0xd7;
// SOF0 to SOF15, except DHT (C4), JPG (C8) and DAC (CC), which share the range.
const isSof = (m: number): boolean => m >= 0xc0 && m <= 0xcf && m !== 0xc4 && m !== 0xc8 && m !== 0xcc;

function parseFrame(p: Uint8Array): Frame {
  const count = p[5];
  const components = Array.from({ length: count }, (_, i) => ({ id: p[6 + 3 * i], h: p[7 + 3 * i] >> 4, v: p[7 + 3 * i] & 15 }));
  return {
    height: (p[1] << 8) | p[2],
    width: (p[3] << 8) | p[4],
    components,
    mcuWidth: 8 * Math.max(...components.map((c) => c.h)),
    mcuHeight: 8 * Math.max(...components.map((c) => c.v)),
  };
}

export function parseJpeg(bytes: Uint8Array): Jpeg {
  if (bytes.length < 4 || bytes[0] !== 0xff || bytes[1] !== SOI) throw new Error('no start-of-image marker');
  const segments: Segment[] = [];
  const scans: Jpeg['scans'] = [];
  const frames: Frame[] = [];
  let pos = 2;
  for (;;) {
    if (pos + 1 >= bytes.length) throw new Error('no end-of-image marker');
    if (bytes[pos] !== 0xff) throw new Error(`expected a marker at byte ${pos}`);
    while (bytes[pos + 1] === 0xff) pos++; // fill bytes before a marker
    const marker = bytes[pos + 1];
    if (marker === EOI) return { segments, scans, frames, eoi: pos, trailing: bytes.subarray(pos + 2) };
    if (marker === SOI) throw new Error(`a second start-of-image marker at byte ${pos}`);
    if (isRst(marker) || marker === 0x01) {
      pos += 2;
      continue;
    }
    const length = (bytes[pos + 2] << 8) | bytes[pos + 3];
    if (length < 2 || pos + 2 + length > bytes.length) throw new Error(`segment FF${hex(marker)} at byte ${pos} runs past the end`);
    const payload = bytes.subarray(pos + 4, pos + 2 + length);
    segments.push({ marker, offset: pos, payload });
    if (isSof(marker)) frames.push(parseFrame(payload));
    pos += 2 + length;
    if (marker === SOS) {
      // Entropy-coded data runs to the next marker that is neither a stuffed FF 00 nor a restart marker.
      const start = pos;
      while (pos + 1 < bytes.length && !(bytes[pos] === 0xff && bytes[pos + 1] !== 0x00 && !isRst(bytes[pos + 1]))) pos++;
      scans.push({ start, end: pos });
    }
  }
}

const hex = (n: number): string => n.toString(16).toUpperCase().padStart(2, '0');
const latin1 = (b: Uint8Array): string => String.fromCharCode(...b);

/** The APPn identifier, such as "Exif" or "ICC_PROFILE": the text before the first zero byte. */
export function appIdentifier(s: Segment): string {
  const end = s.payload.indexOf(0);
  return latin1(s.payload.subarray(0, end < 0 ? Math.min(s.payload.length, 32) : Math.min(end, 32)));
}

export function segmentName(s: Segment): string {
  if (s.marker >= 0xe0 && s.marker <= 0xef) return `APP${s.marker - 0xe0} (${appIdentifier(s)})`;
  if (s.marker === 0xfe) return 'COM';
  return `FF${hex(s.marker)}`;
}

// What a freshly encoded baseline or progressive JPEG needs, and nothing more.
const CODING = new Set([0xc0, 0xc1, 0xc2, 0xc4, 0xdb, 0xdd, SOS]);

/**
 * Everything in the file beyond the compressed picture itself: metadata segments (EXIF, XMP,
 * ICC, IPTC, C2PA, maker notes and any other APPn), comments, thumbnails, extra frames, and bytes
 * after the end-of-image marker. Returns one line per problem; an empty list means a clean file.
 */
export function hiddenDataProblems(bytes: Uint8Array): string[] {
  let jpeg: Jpeg;
  try {
    jpeg = parseJpeg(bytes);
  } catch (e) {
    return [`not a well-formed JPEG: ${(e as Error).message}`];
  }
  const problems: string[] = [];
  for (const s of jpeg.segments) {
    if (s.marker === 0xe0 && appIdentifier(s) === 'JFIF') {
      // JFIF header: identifier (5), version (2), units (1), densities (4), thumbnail width and
      // height (1 + 1), then 3 bytes per thumbnail pixel. Any further bytes are data of their own.
      const thumbnail = 3 * s.payload[12] * s.payload[13];
      if (thumbnail > 0) problems.push(`JFIF thumbnail at byte ${s.offset}`);
      if (s.payload.length !== 14 + thumbnail) problems.push(`JFIF header of ${s.payload.length} bytes at byte ${s.offset}`);
    } else if (!CODING.has(s.marker)) {
      problems.push(`${segmentName(s)} segment, ${s.payload.length} bytes, at byte ${s.offset}`);
    }
  }
  if (jpeg.frames.length !== 1) problems.push(`${jpeg.frames.length} frames instead of 1`);
  if (jpeg.trailing.length > 0) problems.push(`${jpeg.trailing.length} bytes after the end-of-image marker`);
  return problems;
}

export function frameOf(bytes: Uint8Array): Frame {
  const { frames } = parseJpeg(bytes);
  if (frames.length !== 1) throw new Error(`expected one frame, found ${frames.length}`);
  return frames[0];
}

/** Builds a marker segment: FF, marker, 16-bit length (payload + 2), payload. */
export function segment(marker: number, payload: Uint8Array): Uint8Array {
  if (payload.length + 2 > 0xffff) throw new Error(`payload too long for one segment: ${payload.length} bytes`);
  const out = new Uint8Array(4 + payload.length);
  out.set([0xff, marker, (payload.length + 2) >> 8, (payload.length + 2) & 0xff]);
  out.set(payload, 4);
  return out;
}
