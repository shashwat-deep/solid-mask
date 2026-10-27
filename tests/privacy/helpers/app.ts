// Drives the app as a person does: wait until it is ready, choose a photo, wait for the blocks,
// tap Save. Button names are the README's ("Choose photos", "Save").
import { readFile } from 'node:fs/promises';
import { expect, type Locator, type Page } from '@playwright/test';
import { APP_URL } from '../../env.ts';

// Loading the face detector, or masking a 12-megapixel photo, can take a while on a slow machine.
const SLOW = { timeout: 120_000 };

export const chooseButton = (page: Page): Locator => page.getByRole('button', { name: 'Choose photos', exact: true });
export const saveButton = (page: Page): Locator => page.getByRole('button', { name: 'Save', exact: true });

/** Opens the app and waits until it is ready. From then on it must work without a connection. */
export async function openApp(page: Page): Promise<void> {
  const response = await page.goto(APP_URL);
  expect(response?.status(), `the app is served at ${APP_URL}`).toBe(200);
  await expect(chooseButton(page), 'the app gets ready to choose photos').toBeEnabled(SLOW);
}

export type SavedCopy = { name: string; bytes: Uint8Array };

type Watched = { __saveWentOff?: boolean };

/** Chooses one photo, waits until its faces are covered, and saves the copy. */
export async function maskAndSave(page: Page, photoPath: string): Promise<SavedCopy> {
  // Save must go off as soon as a photo is chosen, so the previous photo can't be saved in its
  // place. Watch for that from before the choice: in some engines setFiles() returns only after
  // the photo has been masked and Save is on again.
  await expect(saveButton(page), 'the page has a Save button').toHaveCount(1);
  await saveButton(page).evaluate((button: HTMLButtonElement) => {
    const watched = window as Watched;
    watched.__saveWentOff = button.disabled;
    new MutationObserver(() => {
      if (button.disabled) watched.__saveWentOff = true;
    }).observe(button, { attributeFilter: ['disabled'] });
  });
  const chooser = page.waitForEvent('filechooser');
  await chooseButton(page).click();
  await (await chooser).setFiles(photoPath);
  await expect
    .poll(() => page.evaluate(() => (window as Watched).__saveWentOff), { message: 'Save went off when the photo was chosen' })
    .toBe(true);
  await expect(saveButton(page), 'the photo is masked and ready to save').toBeEnabled(SLOW);
  const download = page.waitForEvent('download');
  await saveButton(page).click();
  const saved = await download;
  return { name: saved.suggestedFilename(), bytes: new Uint8Array(await readFile(await saved.path())) };
}
