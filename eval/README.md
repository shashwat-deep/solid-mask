# Evaluation

The scripts here measure how often the tool leaves a face uncovered, following [`docs/eval-protocol.md`](../docs/eval-protocol.md), part B. The test images are never committed. The manifest lists them, and the scripts download them into `data/`, which git ignores.

## Files

- `manifest/images.csv`: the test images, 200 in the tune split and 800 in the report split. For each: where it comes from, its licence, author and title as Open Images lists them, its Flickr page, the SHA-256 of the file, the width and height of the upright image, and its Rotation.
- `manifest/faces.csv`: one row per face box. `x, y, w, h` are pixels of the upright image; the `Norm` columns are Open Images' own coordinates, which refer to the image as stored. Also Open Images' occluded, truncated and depiction flags, and `yaw`, empty until labelled.
- `manifest/luma.csv`: the mean luma of each face, for the measured-light breakdown. `face_luma.py` writes it; run it again whenever the manifest changes.
- `manifest/review.csv`: the review's decisions, one row per image: `keep`, or `remove` with a reason code (`intimate`, `doubtful` or `unboxed-face`), and who reviewed it. It never describes an image.
- `build_manifest.py`: draws the test set from Open Images V7 and writes the two manifests.
- `download.py`: downloads the images and checks their SHA-256s.
- `review_sheet.py`: makes a page on your computer that shows the images upright with their face boxes, for the review and the rotation check.
- `run_detect.py`: runs the detector on the test images in headless Chromium, through the app's eval page, and writes a detections file.
- `stub/`: a stand-in for the app's eval page with the same interface, used until that page exists and by the tests.
- `score.py`: scores a detections file against the manifest: missed faces, faces covered completely, detection recall and false masks, each with a 95% confidence interval, and the operating point.
- `transforms.py`: the rotation and darkening transforms, their parameters, and the geometry of a rotation, which `score.py` uses.
- `yaw_sheet.py`: makes a page for labelling the yaw of the sample faces.
- `yaw_agreement.py`: compares the two authors' yaw labels (Cohen's κ) and writes the settled labels into `manifest/faces.csv`.
- `labels/`: each author's yaw labels, and the faces they disagreed on.
- `face_luma.py`: measures how bright each face is (mean luma inside its box).
- `check_files.py`: check E2, the structure of saved files, segment by segment.
- `render_copies.py`: check E3, part 1: saves each test image through the eval page as the app saves it, masked and unmasked.
- `hash_distance.py`: check E3, part 2: how far each saved copy is from its original under PDQ and pHash.
- `pdq.py`: PDQ, Meta's perceptual hash, written in numpy; `tests/pdq_reference.csv` lists the eight images and hashes of Meta's regression test that it reproduces.
- `check_colour.py`: checks that the images the transforms start from have the pixels Chromium decodes.
- `tests/`: tests for these scripts (pytest).

The columns follow [`docs/contracts.md`](../docs/contracts.md), section 6.

## Run it

You need Python 3.13 and [uv](https://docs.astral.sh/uv/). From the top folder of the repository:

```bash
uv venv --python 3.13 .venv
uv pip sync --python .venv/bin/python eval/requirements.txt
.venv/bin/python eval/download.py
.venv/bin/python -m pytest eval/tests
```

`download.py` fetches the 1,000 images, about 290 MB, into `data/openimages/images/` and stops with an error if any file differs from its SHA-256 in the manifest.

## Detection runs

`run_detect.py` opens the app's eval page (`app/eval.html`, [`docs/contracts.md`](../docs/contracts.md), section 3) in headless Chromium with Playwright and calls the page's own decoding and detection for every image, so the numbers come from the code the app ships:

```bash
.venv/bin/python -m playwright install --only-shell chromium
.venv/bin/python eval/run_detect.py --page http://localhost:5173/eval.html
.venv/bin/python eval/run_detect.py --page http://localhost:5173/eval.html --tiles 1920,0.25
.venv/bin/python eval/run_detect.py --page http://localhost:5173/eval.html --split report \
    --transforms none,rot0,rot15,rot30,rot45,rot90,rot135,rot180,dark1,dark2,dark3,dark4
```

The app's eval page does not exist yet. Until it does, the default `--page stub` uses `stub/`, which has the same interface but whose "detector" only finds solid magenta rectangles; the tests draw their made-up faces that way. A stub run measures nothing, so it goes to `data/stub-runs/`, never to `results/`.

The runner gives each image to the page itself, on the page's own address, so nothing is sent anywhere, and it stops the run if the page asks for anything from another site. With the app's real eval page it runs only on images that `manifest/review.csv` keeps, since part B runs no detector on an image before it is reviewed. Open Images stores a few images turned; the runner gives those an EXIF orientation tag, in place of any EXIF data they have, so the app's decoding turns them upright as it would a phone photo, and it checks every decoded size against the manifest. It refuses a file whose own EXIF orientation is not 1 or cannot be read; the manifest leaves those out. With `--transforms`, the runner also makes each rotated or darkened copy (`transforms.py`, protocol part B) just before the page asks for it, and keeps none of them. It starts from the image converted to sRGB by its ICC profile, as Chromium converts it; `check_colour.py` checks that the two agree within 1 for test images with each kind of profile, and is worth rerunning after updating Chromium or Pillow. Each run writes `results/detections/<run-id>.jsonl` (section 4 of the contract) and `<run-id>.run_info.json`, with the versions, hashes and timings. Two runs with the same versions must give the same `boxesSha256`, the SHA-256 of every line after the run line. `servedSha256` covers every image the runner gave the page, so when two runs differ it shows whether their images did.

## Scoring

`score.py` reads a detections file in the format of [`docs/contracts.md`](../docs/contracts.md), section 4, and applies the padding and the score threshold itself, so trying other values needs no new run:

```bash
.venv/bin/python eval/score.py results/detections/<run-id>.jsonl --operating-point
.venv/bin/python eval/score.py results/detections/<run-id>.jsonl --pad 0.10 --threshold 0.50 --split report
```

The first finds the padding and threshold on the tune split by the protocol's rule; the second scores the report split at those values. Each transform and setting in the file is scored on its own. A mask covers whole pixels, rounded outward as the app paints it, and a face's covered share is computed exactly from those pixels, so a face turned by a rotation transform needs no special case. Besides face size, occlusion, truncation and yaw, it breaks the miss rate down into the darkest tenth of faces by mean luma (`manifest/luma.csv`) and the rest. The summary is JSON (`--out`); `--faces` also writes one row per face for further breakdowns.

## Yaw labels

Each of us labels the same 600 faces alone, once the test set is frozen ([`docs/eval-protocol.md`](../docs/eval-protocol.md), part B, "Breakdowns"):

1. `.venv/bin/python eval/yaw_sheet.py --labeller <your name>` writes `data/yaw/<your name>/index.html`. Open it, label each face with the keys 1 to 4, and save the box at the bottom as `labels/yaw-<your name>.csv`. You can stop and go on later: the page shows only the faces the file doesn't label yet. Don't open the other author's file until you have both finished.
2. `.venv/bin/python eval/yaw_agreement.py --out results/yaw-agreement.json` reports Cohen's κ with its confidence interval and writes the faces you disagree on to `labels/yaw-disagreements.csv`.
3. Settle each of those together and write the agreed label in its `settled` column.
4. `.venv/bin/python eval/yaw_agreement.py --write` puts the final labels into the `yaw` column of `manifest/faces.csv`, which `score.py` breaks the miss rate down by.

## Privacy checks

Check E2 ([`docs/eval-protocol.md`](../docs/eval-protocol.md), part E) reads saved files segment by segment, with a parser of its own, so a bug in the app's stripping can't hide itself:

```bash
.venv/bin/python eval/check_files.py path/to/saved/files --out results/privacy/e2.json
```

Give it every saved file of a run at once (files or folders), since the protocol allows an ICC profile only if every saved file has the same one. It fails a file for EXIF, XMP, IPTC or C2PA segments, a thumbnail, a differing ICC profile, or bytes after the end of the image. It lists any other segment for us to judge, and exits with an error if any file fails. The report holds segment names and sizes only, never pixels or metadata values.

Check E3 compares each saved copy with its original under two perceptual hashes, the kind reverse image search uses. It needs a detections file of the report split and the operating point, and runs only on reviewed images:

```bash
.venv/bin/python eval/render_copies.py results/detections/<run-id>.jsonl --pad P --threshold T \
    --page http://localhost:5173/eval.html
.venv/bin/python eval/hash_distance.py data/rendered/<render-id>
```

The first saves every report image twice through the eval page's own `render()`: with its masks and, as the control, without. The copies stay in `data/`. The second reports the share of masked copies still within PDQ distance 31 of their original (Meta's matching threshold), with a confidence interval and broken down by how much of the picture is masked, and the full distributions of both distances. The report holds distances only, no hashes or pixels.

## How the test set is drawn

`build_manifest.py` downloads Open Images' image lists and box annotations for its validation and test splits and checks them against fixed SHA-256s. It keeps the images that have at least one "Human face" box, no face box marked IsGroupOf, the CC BY 2.0 licence and a known orientation, and leaves out any whose file carries an EXIF orientation other than 1, or EXIF data it cannot read: the browser would turn such an image by its EXIF orientation, and Open Images' boxes don't say whether they allow for that. Each image's split and its place in the draw come from the SHA-256 of its ID, so they don't depend on which other images are eligible. The set is the first 200 tune and the first 800 report images that the review has not removed.

The images are the copies that the Common Visual Data Foundation (CVDF) hosts for Open Images. Most are at most 1,024 pixels on the long side, with their metadata removed, but a few are larger and keep their EXIF, IPTC and XMP data, and many carry an ICC profile; `build_manifest.py` prints how many are larger and how many carry EXIF data or an ICC profile. Open Images drew its boxes on these copies as stored. A few of them are stored turned on their side or upside down, and Open Images' Rotation column gives the counterclockwise turn that makes each one upright. The manifest gives every box in pixels of the upright image.

## The review

One of us looks at every image before any detector runs on it ([`docs/eval-protocol.md`](../docs/eval-protocol.md), part B, "Review"):

1. `.venv/bin/python eval/review_sheet.py` writes `data/review/index.html` with every image that has not been reviewed yet.
2. Open the page in a browser, choose keep or a reason for removal under each image, and paste the rows from the bottom of the page into `manifest/review.csv`.
3. `.venv/bin/python eval/build_manifest.py` puts the next image of the same split in place of each removed one.
4. Repeat until the build reports no images left to review.

`review_sheet.py --rotated` shows the images that Open Images stores turned, for the check that the boxes line up once the Rotation column is applied.

## Licences and credit

The Open Images annotations are by Google LLC under CC BY 4.0. Open Images lists the images as CC BY 2.0; `manifest/images.csv` credits each one with its author, title and Flickr page, copied from Open Images' metadata. We don't redistribute the images.
