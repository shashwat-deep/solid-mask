import { fetchPhotos } from './fixtures/fetch.ts';
import { writePoisonedPhoto } from './privacy/helpers/poison.ts';

/** Downloads and checks the test photos, then writes the copy that carries planted hidden data. */
export default async function globalSetup(): Promise<void> {
  for (const photo of await fetchPhotos()) await writePoisonedPhoto(photo);
}
