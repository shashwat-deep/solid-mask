// README, "What it never does with your photos":
//   It never keeps your photos. They stay in memory while you work and are gone when you close
//   the page. Nothing from them is written to the browser's storage.
import { expect, test } from '@playwright/test';
import { maskAndSave, openApp, saveButton } from './helpers/app.ts';
import { facesCoveredProblems } from './helpers/pixels.ts';
import { poisonedPhoto } from './helpers/poison.ts';
import { storageProblems } from './helpers/storage.ts';

test('It never keeps your photos: nothing from them in browser storage, and nothing left after closing the page', async ({ context, page }) => {
  const photo = await poisonedPhoto();

  await openApp(page);
  const saved = await maskAndSave(page, photo.path);
  expect(facesCoveredProblems(saved.bytes, photo.faces), 'faces left uncovered in the saved copy').toEqual([]);

  const whileOpen = await storageProblems(page, context);
  expect(whileOpen.problems, 'browser storage after masking and saving a photo').toEqual([]);

  await page.close();
  const reopened = await context.newPage();
  await openApp(reopened);
  await expect(saveButton(reopened), 'nothing to save after the page was closed and opened again').toBeDisabled();
  const afterClose = await storageProblems(reopened, context);
  expect(afterClose.problems, 'browser storage after the page was closed and opened again').toEqual([]);

  for (const reason of new Set([...whileOpen.unavailable, ...afterClose.unavailable])) {
    test.info().annotations.push({ type: 'storage not checked', description: reason });
  }
});
