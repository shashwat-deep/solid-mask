// README, "What it never does with your photos":
//   It never leaves the face in the saved file. The block replaces the face's pixels before the new
//   file is written, so there is nothing underneath to uncover. The new file carries no hidden
//   preview of the original and no leftover data from it.
//
// The photo given to the app carries planted hidden data of every kind (see helpers/poison.ts).
import { expect, test } from '@playwright/test';
import { maskAndSave, openApp } from './helpers/app.ts';
import { frameOf, hiddenDataProblems } from './helpers/jpeg.ts';
import { facesCoveredProblems } from './helpers/pixels.ts';
import { found, POISONED_NAME, poisonedPhoto, samplesFound } from './helpers/poison.ts';

test('It never leaves the face in the saved file: no face pixels, no hidden preview, no leftover data', async ({ page }) => {
  const photo = await poisonedPhoto();

  await openApp(page);
  const saved = await maskAndSave(page, photo.path);

  // The block replaced the face's pixels: inside each face's box the copy is the block colour.
  expect(facesCoveredProblems(saved.bytes, photo.faces), 'faces left uncovered in the saved copy').toEqual([]);
  const frame = frameOf(saved.bytes);
  expect({ width: frame.width, height: frame.height }, 'size of the saved copy').toEqual({ width: photo.width, height: photo.height });

  // No hidden preview and no leftover data: nothing but the picture, which was encoded afresh.
  expect(hiddenDataProblems(saved.bytes), 'hidden data in the saved copy').toEqual([]);
  expect(found(saved.bytes, [...photo.planted, POISONED_NAME.replace(/\.jpg$/, '')]), 'text from the original file').toEqual([]);
  expect(samplesFound(saved.bytes, photo.previewSamples), "pieces of the original's hidden preview").toBe(0);
  expect(samplesFound(saved.bytes, photo.scanSamples), "pieces of the original's compressed picture").toBe(0);
});
