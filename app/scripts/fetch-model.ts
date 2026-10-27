// Downloads the face detector into app/models/ and checks its SHA-256. `npm run dev` and
// `npm run build` run this first; it does nothing when the right file is already there.
import { createHash } from 'node:crypto';
import { mkdir, readFile, rename, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { YUNET } from '../src/pipeline/models.ts';

// The OpenCV Zoo keeps the model in Git LFS; this is the file at the commit that added it.
const SOURCE =
  'https://media.githubusercontent.com/media/opencv/opencv_zoo/f12e12798e8314f7c074a6656816c048dcc95b7a/models/face_detection_yunet/face_detection_yunet_2023mar.onnx';

const path = fileURLToPath(new URL(`../models/${YUNET.file}`, import.meta.url));
const sha256 = (bytes: Uint8Array): string => createHash('sha256').update(bytes).digest('hex');

async function present(): Promise<boolean> {
  try {
    return sha256(await readFile(path)) === YUNET.sha256;
  } catch {
    return false;
  }
}

if (!(await present())) {
  console.log(`Downloading ${YUNET.file} from the OpenCV Zoo…`);
  const response = await fetch(SOURCE, { signal: AbortSignal.timeout(120_000) });
  if (!response.ok) throw new Error(`HTTP ${response.status} from ${SOURCE}`);
  const body = new Uint8Array(await response.arrayBuffer());
  const actual = sha256(body);
  if (actual !== YUNET.sha256) throw new Error(`${YUNET.file} has SHA-256 ${actual}; expected ${YUNET.sha256}`);
  await mkdir(fileURLToPath(new URL('../models/', import.meta.url)), { recursive: true });
  await writeFile(`${path}.part`, body);
  await rename(`${path}.part`, path);
  console.log(`Saved ${path} (SHA-256 checked).`);
}
