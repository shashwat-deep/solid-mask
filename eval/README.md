# Evaluation

The scripts here measure how often the tool leaves a face uncovered, following [`docs/eval-protocol.md`](../docs/eval-protocol.md), part B. The test images are never committed. The manifest lists them, and the scripts download them into `data/`, which git ignores.

## Files

- `manifest/images.csv`: the test images, 200 in the tune split and 800 in the report split. For each: where it comes from, its licence, author and title as Open Images lists them, its Flickr page, the SHA-256 of the file, the width and height of the upright image, and its Rotation.
- `manifest/faces.csv`: one row per face box. `x, y, w, h` are pixels of the upright image; the `Norm` columns are Open Images' own coordinates, which refer to the image as stored. Also Open Images' occluded, truncated and depiction flags, and `yaw`, empty until labelled.
- `manifest/review.csv`: the review's decisions, one row per image: `keep`, or `remove` with a reason code (`intimate`, `doubtful` or `unboxed-face`), and who reviewed it. It never describes an image.
- `build_manifest.py`: draws the test set from Open Images V7 and writes the two manifests.
- `download.py`: downloads the images and checks their SHA-256s.
- `review_sheet.py`: makes a page on your computer that shows the images upright with their face boxes, for the review and the rotation check.
- `run_detect.py`: runs the detector on the test images in headless Chromium, through the app's eval page, and writes a detections file.
- `stub/`: a stand-in for the app's eval page with the same interface, used until that page exists and by the tests.
- `score.py`: scores a detections file against the manifest: missed faces, faces covered completely, detection recall and false masks, each with a 95% confidence interval, and the operating point.
- `transforms.py`: the rotation and darkening transforms, their parameters, and the geometry of a rotation, which `score.py` uses.
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

The runner gives each image to the page itself, on the page's own address, so nothing is sent anywhere, and it stops the run if the page asks for anything from another site. Open Images stores a few images turned; the runner adds an EXIF orientation tag to those, so the app's decoding turns them upright as it would a phone photo, and it checks every decoded size against the manifest. With `--transforms`, the runner also makes each rotated or darkened copy (`transforms.py`, protocol part B) just before the page asks for it, and keeps none of them. It starts from the image converted to sRGB by its ICC profile, as Chromium converts it; `check_colour.py` checks that the two agree within 1 for test images with each kind of profile, and is worth rerunning after updating Chromium or Pillow. Each run writes `results/detections/<run-id>.jsonl` (section 4 of the contract) and `<run-id>.run_info.json`, with the versions, hashes and timings. Two runs with the same versions must give the same `boxesSha256`, the SHA-256 of every line after the run line.

## Scoring

`score.py` reads a detections file in the format of [`docs/contracts.md`](../docs/contracts.md), section 4, and applies the padding and the score threshold itself, so trying other values needs no new run:

```bash
.venv/bin/python eval/score.py results/detections/<run-id>.jsonl --operating-point
.venv/bin/python eval/score.py results/detections/<run-id>.jsonl --pad 0.10 --threshold 0.50 --split report
```

The first finds the padding and threshold on the tune split by the protocol's rule; the second scores the report split at those values. Each transform and setting in the file is scored on its own. A mask covers whole pixels, rounded outward as the app paints it, and a face's covered share is computed exactly from those pixels, so a face turned by a rotation transform needs no special case. The summary is JSON (`--out`); `--faces` also writes one row per face for further breakdowns.

## How the test set is drawn

`build_manifest.py` downloads Open Images' image lists and box annotations for its validation and test splits and checks them against fixed SHA-256s. It keeps the images that have at least one "Human face" box, no face box marked IsGroupOf, the CC BY 2.0 licence and a known orientation. Each image's split and its place in the draw come from the SHA-256 of its ID, so they don't depend on which other images are eligible. The set is the first 200 tune and the first 800 report images that the review has not removed.

The images are the copies that the Common Visual Data Foundation (CVDF) hosts for Open Images: at most 1,024 pixels on the long side, with all metadata removed. Open Images drew its boxes on these copies as stored. A few of them are stored turned on their side or upside down, and Open Images' Rotation column gives the counterclockwise turn that makes each one upright. The manifest gives every box in pixels of the upright image.

## The review

One of us looks at every image before any detector runs on it ([`docs/eval-protocol.md`](../docs/eval-protocol.md), part B, "Review"):

1. `.venv/bin/python eval/review_sheet.py` writes `data/review/index.html` with every image that has not been reviewed yet.
2. Open the page in a browser, choose keep or a reason for removal under each image, and paste the rows from the bottom of the page into `manifest/review.csv`.
3. `.venv/bin/python eval/build_manifest.py` puts the next image of the same split in place of each removed one.
4. Repeat until the build reports no images left to review.

`review_sheet.py --rotated` shows the images that Open Images stores turned, for the check that the boxes line up once the Rotation column is applied.

## Licences and credit

The Open Images annotations are by Google LLC under CC BY 4.0. Open Images lists the images as CC BY 2.0; `manifest/images.csv` credits each one with its author, title and Flickr page, copied from Open Images' metadata. We don't redistribute the images.
