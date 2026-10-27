// README, "What it never does with your photos":
//   It never changes your original. It saves a new file with a plain name such as `masked-1.jpg`.
import { createHash } from 'node:crypto';
import { copyFile, mkdtemp, readFile, rm, stat } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { expect, test } from '@playwright/test';
import { maskAndSave, openApp } from './helpers/app.ts';
import { facesCoveredProblems } from './helpers/pixels.ts';
import { POISONED_NAME, poisonedPhoto } from './helpers/poison.ts';

async function fingerprint(path: string): Promise<{ sha256: string; size: number; modified: number }> {
  const [bytes, info] = await Promise.all([readFile(path), stat(path)]);
  return { sha256: createHash('sha256').update(bytes).digest('hex'), size: info.size, modified: info.mtimeMs };
}

test('It never changes your original: the photo is untouched, and each copy is a new file named masked-N.jpg', async ({ page }) => {
  const photo = await poisonedPhoto();
  // A short path of its own: Windows browsers can't read files whose path is over 260 characters.
  const folder = await mkdtemp(join(tmpdir(), 'solid-mask-'));
  try {
    const original = join(folder, POISONED_NAME);
    await copyFile(photo.path, original);
    const before = await fingerprint(original);

    await openApp(page);
    const first = await maskAndSave(page, original);
    const second = await maskAndSave(page, original);
    expect(facesCoveredProblems(first.bytes, photo.faces), 'faces left uncovered in the saved copy').toEqual([]);

    expect([first.name, second.name], 'names of the saved copies').toEqual(['masked-1.jpg', 'masked-2.jpg']);
    expect(await fingerprint(original), 'the original file after masking and saving it twice').toEqual(before);
    expect(Buffer.compare(first.bytes, await readFile(original)), 'the saved copy is a new file, not the original').not.toBe(0);
  } finally {
    await rm(folder, { recursive: true, force: true });
  }
});
