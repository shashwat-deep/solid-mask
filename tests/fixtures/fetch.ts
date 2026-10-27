// Downloads the photos listed in photos.csv into fixtures/data/ and checks each one's SHA-256.
// Test photos are never committed (CLAUDE.md, rule 3): this manifest and this script are.
// The Playwright global setup calls it; `npm run fixtures` runs it on its own.
import { createHash } from 'node:crypto';
import { mkdir, readFile, rename, writeFile } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { FIXTURES, FIXTURE_DATA } from '../env.ts';

export type Photo = {
  imageId: string;
  url: string;
  landingUrl: string;
  licence: string;
  author: string;
  title: string;
  sha256: string;
  bytes: number;
  width: number;
  height: number;
  /** Where the downloaded file is kept. */
  path: string;
};

/** The core of a face, eyebrows to below the mouth and cheek to cheek, in pixels of the upright photo. */
export type Face = { imageId: string; faceId: string; x: number; y: number; w: number; h: number };

// Wikimedia asks automated clients to say who they are.
const USER_AGENT = 'solid-mask-tests (https://github.com/shashwat-deep/solid-mask)';

/** Parses CSV with a header row (RFC 4180: quoted fields may hold commas, quotes and newlines). */
export function parseCsv(text: string): Record<string, string>[] {
  const rows: string[][] = [];
  let row: string[] = [];
  let field = '';
  let quoted = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (quoted) {
      if (c === '"' && text[i + 1] === '"') {
        field += '"';
        i++;
      } else if (c === '"') {
        quoted = false;
      } else {
        field += c;
      }
    } else if (c === '"') {
      quoted = true;
    } else if (c === ',') {
      row.push(field);
      field = '';
    } else if (c === '\n' || c === '\r') {
      if (c === '\r' && text[i + 1] === '\n') i++;
      row.push(field);
      rows.push(row);
      row = [];
      field = '';
    } else {
      field += c;
    }
  }
  if (field !== '' || row.length > 0) rows.push([...row, field]);
  const [header, ...body] = rows.filter((r) => r.length > 1 || r[0] !== '');
  return body.map((r) => Object.fromEntries(header.map((name, i) => [name, r[i] ?? ''])));
}

const sha256 = (bytes: Uint8Array): string => createHash('sha256').update(bytes).digest('hex');

export async function readPhotos(): Promise<Photo[]> {
  const rows = parseCsv(await readFile(join(FIXTURES, 'photos.csv'), 'utf8'));
  return rows.map((r) => ({
    imageId: r.imageId,
    url: r.url,
    landingUrl: r.landingUrl,
    licence: r.licence,
    author: r.author,
    title: r.title,
    sha256: r.sha256,
    bytes: Number(r.bytes),
    width: Number(r.width),
    height: Number(r.height),
    path: join(FIXTURE_DATA, `${r.imageId}.jpg`),
  }));
}

export async function readFaces(imageId: string): Promise<Face[]> {
  const rows = parseCsv(await readFile(join(FIXTURES, 'faces.csv'), 'utf8'));
  return rows
    .filter((r) => r.imageId === imageId)
    .map((r) => ({ imageId: r.imageId, faceId: r.faceId, x: Number(r.x), y: Number(r.y), w: Number(r.w), h: Number(r.h) }));
}

async function hasHash(path: string, expected: string): Promise<boolean> {
  try {
    return sha256(await readFile(path)) === expected;
  } catch {
    return false;
  }
}

/** Makes sure every photo in the manifest is in fixtures/data/ with the right SHA-256. */
export async function fetchPhotos(): Promise<Photo[]> {
  const photos = await readPhotos();
  await mkdir(FIXTURE_DATA, { recursive: true });
  for (const photo of photos) {
    if (await hasHash(photo.path, photo.sha256)) continue;
    const response = await fetch(photo.url, { headers: { 'User-Agent': USER_AGENT }, signal: AbortSignal.timeout(120_000) });
    if (!response.ok) throw new Error(`${photo.imageId}: HTTP ${response.status} from ${photo.url}`);
    const body = new Uint8Array(await response.arrayBuffer());
    const actual = sha256(body);
    if (actual !== photo.sha256) {
      throw new Error(
        `${photo.imageId}: downloaded file has SHA-256 ${actual}, but photos.csv says ${photo.sha256}. ` +
          `The file at ${photo.landingUrl} may have been replaced.`,
      );
    }
    await writeFile(`${photo.path}.part`, body);
    await rename(`${photo.path}.part`, photo.path);
  }
  return photos;
}

const runDirectly = resolve(process.argv[1] ?? '').toLowerCase() === fileURLToPath(import.meta.url).toLowerCase();
if (runDirectly) {
  for (const photo of await fetchPhotos()) console.log(`${photo.imageId}: ${photo.path} (SHA-256 checked)`);
}
