# Evaluation protocol

Draft for M0. Owner: Shashwat Deep; reviewer: Pratyush. Both authors agreed on every value below on 27 October 2026. Everything here is fixed before the first evaluation run. Any later change goes into the paper's list of deviations from the protocol, with its reason.

## A. Questions

1. How often does the tool leave a face uncovered, and how does that change with face size, angle, occlusion and light?
2. Which detector should version 1 ship, YuNet or YOLO5Face-n?
3. How many seconds does a photo take in phone browsers, and how much slower is the browser than native code on the same machine?
4. Does a saved file keep anything beyond the visible, covered picture that could identify the person? (threat model, checks E1 to E3)

## B. Missed faces

### Data

- Source: Open Images V7, validation and test splits: images with at least one "Human face" box (label `/m/0dzct`). The annotations are under CC BY 4.0. Open Images lists the images as CC BY 2.0; each image's licence, author and title are copied from Open Images' image metadata into the manifest (`docs/contracts.md`, §6). The image files are the copies that the Common Visual Data Foundation (CVDF) hosts for Open Images. Most are at most 1,024 px on the long side, with their metadata removed, but a few are larger and keep their EXIF, IPTC and XMP data, and many carry an ICC profile; `eval/build_manifest.py` prints how many are larger and how many carry EXIF data or an ICC profile.
- Exclusions: images with any face box marked IsGroupOf (the faces inside are not boxed one by one); images whose orientation Open Images does not give (an empty Rotation value, which Open Images uses for images that were no longer on Flickr in 2018 and, in its metadata, also for every image whose title contains a comma); images whose file carries an EXIF orientation other than 1, or EXIF data that cannot be read (the browser turns an image by its EXIF orientation, and Open Images' boxes and Rotation value do not say whether they allow for it); and images removed in the review below.
- Orientation: Open Images drew its boxes on the image as stored, and its Rotation column gives the counterclockwise turn (0°, 90°, 180° or 270°) that makes the image upright. The manifest gives every box in pixels of the upright image, and the detector is given the upright image: the runner gives each image stored turned an EXIF orientation tag, in place of any EXIF data the file has, so the app's own decoding turns it upright, as it does a phone photo, and checks each decoded size against the manifest.
- Review: one author looks at every sampled image before any detector runs on it, and removes it if it is intimate or sexual (reason code `intimate`), if there is any doubt about that (`doubtful`), or if a visible face has no box (`unboxed-face`). The other author checks a random 10% of the decisions. Decisions are logged in `eval/manifest/review.csv` with the reason code and no description of the image.
- Size: 1,000 images after review, 200 in the tune split and 800 in the report split. Before the review, the images drawn hold 1.8 faces each on average, so the set has about 1,800 faces.
- Draw: an image is in the tune split when the SHA-256 of `solid-mask:split:0:<imageId>`, read as a number, is divisible by 5 (about 20% of the eligible images), and in the report split otherwise. Within each split, the images are ranked by the SHA-256 of `solid-mask:order:0:<imageId>`. The set is the first 200 tune and the first 800 report images in these rankings that the review keeps.
- Split: the tune split is used only to set the padding, the score threshold and the bake-off decision. The report split gives every number in the paper.
- Before scoring, check on at least 10 images that the boxes line up with the faces once the Rotation column is applied.
- Frozen at M2: the manifest and the SHA-256 of every image are committed, and nothing is added or removed afterwards.

### Definitions

- Mask: a detected box with a score at or above the threshold, grown by `pad`, rounded outward to whole pixels and clipped to the image (`docs/contracts.md`, §2): the pixels the app paints.
- Protected face: the union of masks covers at least 90% of the face's annotated box. Coverage is computed on rasterised masks at the image's resolution, which also handles rotated boxes: the share of the face's box, or of its rotated quadrilateral, that lies inside the masks' pixels, computed exactly.
- Missed face: a face that is not protected. Miss rate = missed faces / all faces. Depictions are counted on their own (Breakdowns).
- Also reported: the share of faces covered completely, and the share matched by a detected box at IoU ≥ 0.5, the usual detection recall, for comparison with published results. For this match the boxes are taken before padding and clipped to the image, in order of score, and each box matches at most one face, the unmatched face it overlaps most.
- False mask: a mask with IoU below 0.1 against every annotated face, depictions included. Reported per image.
- Uncertainty: 95% confidence intervals from a bootstrap over images, since faces in the same photo are not independent; 10,000 resamples of the images, drawn with numpy's `default_rng(0)`, the same resamples for every value from one run and setting; the interval runs from the 2.5th to the 97.5th percentile. For a breakdown, resamples that hold none of its faces are left out of its interval, and their number is reported with it.

### Operating point, set on the tune split

- Padding: the smallest `pad`, in steps of 0.05, at which at least 99% of the faces found at IoU ≥ 0.5 are covered completely.
- Score threshold: the lowest threshold at which false masks stay at or below 0.25 per image. A false mask costs the user one tap, while a missed face can cost them their privacy, so the rule favours finding faces.
- The two are set together, for each detector and setting, on the tune images without a transform. For each threshold from 0.05 to 0.99 in steps of 0.01, the padding is the smallest `pad` from 0 to 1 that meets the padding rule at that threshold, counting faces that are not depictions. The operating point is the lowest threshold whose false masks, with its padding, meet the threshold rule. `eval/score.py --operating-point` applies this.

### Settings compared

- single: the whole image, resized so its long side is 640 px; one pass.
- tiled: the image resized so its long side is 1,920 px (smaller images are not enlarged), cut into 640 px tiles that overlap by 25%, with boxes merged by NMS. Most Open Images copies are at most 1,024 px on the long side, so in part B the tiled setting runs most images at their own size; the speed test (part D) uses photos of about 12 MP.

### Breakdowns

Each is reported as a miss rate with its 95% CI on the report split.

- Face size: face height as a share of the image's long side: under 2%, 2 to 5%, 5 to 10%, 10 to 25%, 25% and over. In the single setting, 2% is about 13 px at the detector's input.
- Occlusion and truncation: Open Images' IsOccluded and IsTruncated flags.
- Depictions (faces on posters, paintings or statues, flagged IsDepiction): reported separately and left out of the headline rate.
- Yaw, the face's turn away from the camera: a random sample of 600 faces from the report split, each labelled frontal (both eyes visible, face mostly towards the camera), three-quarter (both eyes visible, face clearly turned), profile (one eye or none visible) or unclear. Both authors label independently, from face crops shown without any detector output. We report Cohen's κ, then settle disagreements together. Unclear faces are left out of this breakdown.
  - The sample is the first 600 report-split faces that are not depictions, in the order of the SHA-256 of `solid-mask:yaw:0:<imageId>:<faceId>`. Labelling starts once the test set is frozen, so the sample no longer changes.
  - Each crop is a square twice the longer side of the face's box, centred on it, cut from the upright image, with ticks at the corners of the box (`eval/yaw_sheet.py`).
  - Each author's labels go in a file of their own in `eval/labels/`. Neither author opens the other's file until both are complete.
  - κ is Cohen's unweighted κ over the four labels, with a 95% confidence interval from the bootstrap over images; we also report κ over the faces neither author called unclear (`eval/yaw_agreement.py`). The settled labels go into the `yaw` column of `eval/manifest/faces.csv`.
- In-plane rotation: every report-split image rotated counterclockwise by 0°, 15°, 30°, 45°, 90°, 135° and 180° on a canvas enlarged to fit, with the annotated boxes rotated as polygons. The rotation is Pillow's `Image.rotate` with bicubic resampling; the corners it uncovers are mid-grey (128, 128, 128); 90° and 180° are exact transposes. The 0° copy goes through the same steps and is the control for the series.
- Light, synthetic: every report-split image darkened by 1, 2, 3 and 4 EV: converted to linear RGB (IEC 61966-2-1), scaled by 2^−EV, given Poisson–Gaussian noise, clipped to [0, 1] and converted back to 8-bit sRGB. For a linear value x, the noise is a Poisson count with mean x / λ_shot, times λ_shot, plus Gaussian noise with variance λ_read, so its variance is λ_read + λ_shot·x, the sensor model of Brooks et al. (CVPR 2019, Eq. 1). They fitted log λ_shot to a uniform distribution on [log 0.0001, log 0.012] and log λ_read = 2.18 log λ_shot + 1.2 on the Darmstadt Noise Dataset; we take the middle of that range, λ_shot = 0.0011, and the fitted line, λ_read = 1.17 × 10⁻⁶. The noise is drawn per pixel and channel, with a random generator for each image and level seeded from its ID and the level.
- Both transforms start from the image as Chromium decodes it: the runner converts it to sRGB with its ICC profile, as Chromium does (`eval/check_colour.py` checks that the pixels agree within 1 for test images with each kind of profile), turns it upright, transforms it and gives it to the page as a PNG.
- Light, measured: the darkest tenth of faces by mean luma inside the box, against the rest. Luma is Y′ = 0.299 R′ + 0.587 G′ + 0.114 B′ (BT.601, as JPEG stores it), on 0 to 255, of the image as Chromium decodes it, averaged over the pixels whose centres lie inside the face's box (`eval/face_luma.py` writes `eval/manifest/luma.csv`). The darkest tenth is the ⌈n/10⌉ faces with the lowest mean luma among the n faces scored, ties broken by image and face ID.
- Light, real: about 40 photos of the two authors taken in dim light, with the light level read in lux from a phone light-meter app and the faces boxed by both authors. With two people and few faces, this is reported as counts, as a check on the synthetic results, without confidence intervals.

## C. Bake-off, at M2, on the tune split

- Candidates: YuNet (`face_detection_yunet_2023mar.onnx` from the OpenCV Zoo, MIT) and YOLO5Face-n (exported to ONNX from deepcam-cn/yolov5-face, GPL-3.0, and kept out of the repo). Each runs at its own operating point, in both settings.
- Speed target: a median of at most 2 s per 12 MP photo, after the first photo, on the slowest phone in the bench (part D).
- Rule: among the detector-and-setting pairs that meet the speed target, ship the one that protects the most faces on the tune split. If YuNet comes within 1 percentage point of the best, ship YuNet, which is MIT-licensed and a smaller download. If no pair meets the target, ship the fastest pair and report the shortfall as a limitation.
- If YOLO5Face-n is chosen, the code moves to GPL-3.0 before the model is served.

## D. Speed

- Bench photos: about 20 openly licensed photos of people at about 12 MP from Wikimedia Commons (`app/bench/manifest.csv`, with each photo's licence and author).
- Measured per photo with `performance.now()`: decode, detect, mask and encode, and total. The first photo of a run is reported on its own, since it includes loading and compiling the model.
- Configurations: YuNet, YOLO5Face-n, and YOLO5Face-s (the model Ente uses, loaded from a local file); the single and tiled settings; single-threaded WASM, multi-threaded WASM where the page is cross-origin isolated, and WebGPU where the browser has it.
- Devices: every phone the authors have, at least one low-end Android phone if one can be borrowed, and both laptops. Model, OS and browser versions are recorded.
- Conditions: the page is loaded, then airplane mode is switched on; battery above 50%, not charging, battery saver off; other apps closed; three runs per configuration, with five minutes' rest between runs; configurations in an order shuffled with a fixed seed.
- Native baseline: the same ONNX files in ONNX Runtime for Python on each laptop's CPU, with the same photos and settings. This comparison uses detect time only.
- Reported: the median and interquartile range of per-photo time for each device, browser, backend and configuration, and the browser-to-native ratio of detect time on each laptop, with a bootstrap 95% CI.

## E. Privacy checks

- E1, metadata audit: each author takes 10 photos with location switched on, somewhere public, in every format their phone's camera offers (for example JPEG and HEIC), and saves them through the tool in each browser tested. `exiftool -a -G1 -s` runs on each original and each saved copy. Pass: the saved copy has no GPS, date or time, make, model or serial number, lens, software, maker notes, XMP, IPTC, C2PA or thumbnail fields, and a generic name. The exiftool reports are committed with coordinates removed; the photos are not.
- E2, file structure: every saved file from E1 and from the privacy suite is parsed segment by segment. Pass: no APP1 (EXIF or XMP), APP11 (C2PA/JUMBF) or APP13 (IPTC) segments and no thumbnail; an ICC profile only if it is the browser's own, identical in every saved file whatever the input; and no bytes after the JPEG end marker (or the PNG IEND chunk). For a PNG, the same rule rules out eXIf, tEXt, zTXt, iTXt, tIME and caBX (C2PA) chunks. Any other segment or chunk that the picture does not need, such as a comment, is listed for the authors to judge. `eval/check_files.py` applies the rule, from its own parser, to all the saved files of a run together, so that it can compare their ICC profiles.
- E3, perceptual-hash distance: for every report-split image, the distance between the original and the saved copy (masked at the chosen operating point and encoded by the app's own `render`, `docs/contracts.md` §3) with PDQ, Meta's 256-bit perceptual hash, and with pHash (64-bit, the `imagehash` package). Reported: the share of saved copies within PDQ distance 31 of their original, the threshold in Meta's PDQ documentation, with a bootstrap 95% CI, broken down by the share of the picture that is masked; the full distributions for both hashes; and, as a control, the distances after re-encoding without masks. The original is the image as Chromium decodes it, upright and in sRGB. PDQ comes from `eval/pdq.py`, which gives the same hashes as Meta's C++ reference on its eight regression images (distance 0), after shrinking each picture to at most 512 px a side, keeping its shape, as Meta's Python reference does; pHash comes from `imagehash.phash`. The masked share is the share of the picture's pixels under the masks, in bins of none, under 1%, 1–5%, 5–10%, 10–25%, and 25% and over. Originals with a PDQ quality of 49 or less, which Meta advises discarding, are counted and reported. `eval/render_copies.py` saves the copies through the eval page and `eval/hash_distance.py` measures them.

## F. Reporting rules

- Every number comes from committed script output (`eval/paper_numbers.py` → `paper_numbers.txt`).
- Every run is kept in `results/` with its run line (`docs/contracts.md`, §4), including runs that are not reported.
- Results that go against our expectations are reported in the same way as the rest.
- Reproducibility: the other author reruns the report-split evaluation from the manifest. With single-threaded WASM and the same versions, the detection files must match byte for byte after the run line, which names the run; their SHA-256s are recorded (`boxesSha256` in each run's `run_info.json`).

## G. Data ethics

- Only openly licensed, non-intimate images. Test images are never committed or redistributed; the manifest points to the sources and credits the photographers.
- No face recognition is run on any image.
- No test image of a stranger appears in the paper or the demo; figures and the demo show only the two authors.
- The GPS-tagged photos for E1 are taken somewhere public and never committed.
