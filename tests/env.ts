import { fileURLToPath } from 'node:url';

/** Where the test server listens, and the path GitHub Pages serves the app under. */
export const PORT = 4400;
export const BASE_PATH = '/solid-mask/';
export const ORIGIN = `http://127.0.0.1:${PORT}`;
export const APP_URL = `${ORIGIN}${BASE_PATH}`;

/** The production build: the suite tests exactly the files that get deployed. */
export const APP_DIST = fileURLToPath(new URL('../app/dist/', import.meta.url));

export const FIXTURES = fileURLToPath(new URL('./fixtures/', import.meta.url));
/** Downloaded photos and the files made from them. The root .gitignore keeps every `data/` folder out of git. */
export const FIXTURE_DATA = fileURLToPath(new URL('./fixtures/data/', import.meta.url));
