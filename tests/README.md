# Tests

## Unit tests

`unit/` tests the app's pure functions in Node with Vitest, without a browser: the YuNet input tensor (resizing, letterboxing, channel order), the decoding of the model's outputs, non-maximum suppression, the size and painting of the blocks, and the rebuilding of the saved JPEG from the picture alone.

## Privacy suite

`privacy/` holds one Playwright test for each promise in the README's "What it never does with your photos". Each test drives the production build in `app/dist` the way a person would (wait until the page is ready, tap **Choose photos**, wait for the blocks, tap **Save**) in Chromium, Firefox and WebKit. A small server, `server.ts`, serves the build under `/solid-mask/` with no special headers, as GitHub Pages does.

| README promise | Test | What it checks |
|---|---|---|
| It never uploads your photos. | `never-uploads.spec.ts` | Once the page is ready, the browser goes offline. The photo is still masked and saved, and no request, socket, WebRTC or WebTransport channel is opened. |
| It never keeps your photos. | `never-keeps.spec.ts` | After masking and saving, and again after closing and reopening the page: no localStorage, sessionStorage, IndexedDB, cookies or private files, and nothing in the Cache API except the app's own files. |
| It never tracks you. | `never-tracks.spec.ts` | Every request goes to the app's own origin, nothing is blocked, there are no cookies or outside frames, and the Content Security Policy names no other website. |
| It never changes your original. | `never-changes-original.spec.ts` | The chosen file is byte-for-byte unchanged after two saves, and the copies are named `masked-1.jpg` and `masked-2.jpg`. |
| It never leaves the face in the saved file. | `never-leaves-the-face.spec.ts` | Inside each face, the saved pixels are the block colour (within ±2 in whole JPEG blocks). The file holds nothing but the picture: no EXIF, XMP, ICC, IPTC, C2PA or comment segment, no thumbnail, no bytes after the end marker, no text or compressed data from the original. |

Every privacy test first checks that the face in the saved copy is covered, so none of them can pass on a page that does nothing.

`instruments.spec.ts` checks the checks: each one has to catch the problem it looks for.

## Eval page

`app/eval-page.spec.ts` drives the eval page (`app/eval.html`, `docs/contracts.md`, section 3) on the app's development server, as `eval/run_detect.py` does: the test photo is served on the page's own origin and detected with the runner's options. It checks that:

- the boxes match the 7 that OpenCV's FaceDetectorYN finds with the same model scoring 0.10 or more;
- in the tiled setting (`--tiles 1920,0.25`: the photo shrunk to 1440 x 1920 and cut into 12 tiles of 640 x 640 that overlap), the boxes match the 16 scoring 0.10 or more that FaceDetectorYN finds tile by tile, merged with one NMS;
- a copy of the photo stored turned, with the EXIF orientation the runner adds, decodes upright with the face within 2 px;
- `render()` covers the face and writes a file with nothing but the picture;
- `info()` gives the ONNX Runtime version, `wasm`, one thread and the model's SHA-256;
- a reloaded page refuses to start (Vite reloads it when a file changes, which would change the code in the middle of a run);
- the deployed build holds neither the page nor its code.

The OpenCV boxes come from `reference/opencv_yunet.py` and `reference/opencv_yunet_tiles.py`, which write `reference/opencv_yunet.txt` and `reference/opencv_yunet_tiles.txt` (OpenCV 4.13.0, pinned in `reference/requirements.txt`); the tests read those files. `opencv_yunet_tiles.py` was written from a step-by-step description of the tiled setting, without the app's code, so the two implementations check each other. In Chromium, the browser the runner uses, every box scoring 0.10 or more must match within 0.5 px and 0.0005 of score; Firefox and WebKit get 2 px and 0.002, since another engine may decode the JPEG a little differently. Boxes are matched by position, not by rank, since two scores closer than that may trade places.

Playwright starts the development server on port 4402 for these tests.

## Test photos

Test photos are downloaded, never committed (`CLAUDE.md`, rule 3). `fixtures/photos.csv` lists each photo with its source, licence, author and SHA-256, and `fixtures/fetch.ts` downloads it into `fixtures/data/` and refuses it if the hash differs. `fixtures/faces.csv` gives the core of each face, eyebrows to below the mouth and cheek to cheek, in pixels of the upright photo. The face checks use these boxes, so they don't depend on the padding the evaluation chooses.

Before the tests run, `privacy/helpers/poison.ts` writes a copy of each photo named like a phone photo, `IMG_20261027_143015.jpg`, that carries every kind of hidden data the README promises to drop: EXIF with a made-up GPS position at sea, a camera serial number and a small preview of the photo; XMP; IPTC; a C2PA manifest; a comment; the original's ICC profile; and, after the end of the image, a second copy of the preview. Each planted item carries the text `SOLIDMASK-CANARY`. The app is given this copy.

## Run

```bash
cd tests
npm ci
npx playwright install --with-deps chromium firefox webkit
npm test
```

`npm test` first builds `app/` (run `npm ci` there once), then runs the unit tests and the privacy suite. `npm run test:unit` runs the unit tests alone, and `npm run typecheck` checks the types.

## Continuous integration

`.github/workflows/pages.yml` runs `npm test` on every pull request and every push to `main`, on Ubuntu. On `main` it then deploys `app/dist` to GitHub Pages: exactly the build the suite has just tested, so a build that breaks a promise is never deployed.
