> This is the project plan as approved on 2026-10-27. It was written for Shashwat, so "you" means Shashwat Deep, "your teammate" means Pratyush, and "I" means Shashwat's Claude Code session. Change it only through a PR both authors approve.

# Plan: on-device face-masking tool and its software paper

## Context

You and your teammate are writing a software paper about a small privacy tool for people who share photos but want to protect their identity. Version 1 covers every face with a solid mask and strips location and other metadata, entirely on the phone, uploading nothing. Your replication (doi:10.5281/zenodo.23692156) is the evidence for the mask: after two epochs, a small CNN trained on obfuscated MNIST still read 89.28% of σ = 4 blurred digits and 51.15% of 14×14-pixelated ones, while the solid mask stayed at chance (11.35%). That work used digits, so the paper cites McPherson et al. for faces.

**Ente angle.** Ente's mobile and desktop apps detect faces on the device (YOLO5Face small variant + MobileFaceNet in ONNX Runtime, per ente.com/ml), but its help centre says ML features are not available in the web app. The speed test times seconds per photo in phone browsers, including Ente's own detector, so the result shows how well this kind of model runs on the web.

**Decided:** Zenodo + IEEE format, as before · you own evidence and paper; your teammate owns app, tests, bench page and demo · the detector is picked by a bake-off in week 2 (YuNet, MIT, vs YOLO5Face-n, GPL-3.0; the licence follows the pick) · "a model undoing the mask" is answered by argument plus pixel-level tests, with no face recognition run on anyone.

`Computer Vision/` is empty and becomes the new repo (working name `solid-mask`). Reuse the conventions of `../Deep Learning/mnist-obfuscation-replication/`: the README layout (Files / Run it / Results / AI use / Citation / License), `CITATION.cff`, numbers printed by `paper_numbers.py` into `paper_numbers.txt`, hashes recorded as in `run_info.json`, figure scripts like `make_fig_accuracy.py`, pinned `requirements-*.txt`, MIT code + CC BY 4.0 paper.

## How two Claude Code sessions stay in step

- One GitHub repo with your teammate as collaborator. Small PRs; nobody pushes to `main`; the other person reviews (their Claude can run `/code-review` on the PR first).
- `CLAUDE.md` holds the rules below. Both sessions load it automatically, so both Claudes work by the same rules.
- Folder ownership, set in `CLAUDE.md`: `app/`, `tests/` → teammate; `eval/`, `paper/`, `docs/threat-model.md`, `docs/eval-protocol.md` → you; `README.md`, `CLAUDE.md`, `docs/contracts.md` → both. `.github/CODEOWNERS` lists both of you on every path: GitHub never lets authors approve their own PRs, so the other person must approve each one.
- GitHub Issues labelled `app` / `evidence` / `paper`, one milestone per gate (M0–M5).
- This plan is copied to `docs/plan.md` so your teammate's Claude can read it.

**Rules for CLAUDE.md**
1. No app code until M0 (the README gate) is merged.
2. Privacy invariants: no network request after the page loads; no image data in any browser storage; no third-party scripts, fonts, CDNs, analytics or cookies; the mask is drawn into the pixels before encoding. A change that could break one → stop and ask the human.
3. Data: openly licensed, non-intimate images only (your own photos count once you release them under CC BY 4.0). Never commit test images; commit a manifest (ID, URL, licence, author, SHA-256) and a download script. Figures and the demo show only the two authors.
4. Licences: never paste code from Ente (AGPL-3.0) or yolov5-face (GPL-3.0); reading and citing are fine. Never commit or serve YOLO5Face weights unless the bake-off picks it and the repo has moved to GPL-3.0. Runtime dependencies must be MIT, BSD or Apache-2.0.
5. Every number in the paper comes from committed script output (`eval/paper_numbers.py` → `paper_numbers.txt`).
6. Don't edit the other person's folders; open an issue or comment on their PR.
7. Log AI use in `docs/ai-use.md` as you go; it becomes the AI-use section, as in the MNIST paper.

## Repo layout

```
README.md  CLAUDE.md  LICENSE (MIT until the bake-off)  CITATION.cff  .github/CODEOWNERS
docs/     plan.md  threat-model.md  eval-protocol.md  contracts.md  ai-use.md  demo-script.md
app/      Vite + TypeScript PWA; src/pipeline/{decode,detect,mask,encode}.ts; bench.html  (teammate)
tests/    vitest unit tests; Playwright privacy suite                                     (teammate)
eval/     manifests, download + transform scripts, runner, score.py, paper_numbers.py    (you)
results/  committed outputs: detections JSONL, bench JSON, summaries                     (both)
paper/    IEEE source, figures, refs.bib                                                 (you lead)
```

## Contracts (`docs/contracts.md`, agreed at M0)

- `detectFaces(bitmap, {model, inputSize, tiling}) → Box[]` in `app/src/pipeline/detect.ts`; Box = `{x, y, w, h, score}` in pixels of the upright image. Supports `yunet` (bundled) and `yolo5face` (weights loaded from a local file, never bundled).
- Mask = box grown by `pad` on each side (value set by the eval), clipped to the image, drawn opaque in one colour.
- Detections JSONL: `imageId, transform, model, inputSize, tiling, boxes` (raw, before padding).
- Bench JSON, one per device run: device, OS, browser, backend (wasm/webgpu), threads, `crossOriginIsolated`, model, input size, model bytes, first-photo ms, then per photo: decode, detect, mask+encode and total ms.
- Manifest CSV: `imageId, source, url, licence, author, sha256, width, height`, plus one row per face with its box and Open Images flags.

## Milestones

| Gate | Done when | Lead |
|---|---|---|
| M0 · days 1–3 | README, CLAUDE.md, threat model, eval protocol, contracts merged; first correspondence sent | you draft, teammate approves |
| M1 · weeks 1–2 | App masks a photo on GitHub Pages; eval runner scores 100 images | both |
| M2 · weeks 2–3 | Bake-off decided; app feature-complete; privacy suite green in CI; test set frozen | both |
| M3 · weeks 3–4 | Numbers frozen: detection limits, privacy checks, speed on every device | both |
| M4 · weeks 4–5 | Paper draft, two-minute demo, cross-review, any personal communication approved by its source | both |
| M5 | v1.0.0 tag, Zenodo DOI, `CITATION.cff`, paper PDF in the repo | you |

## Phase 0: README first (drafted in this session; your teammate approves)

README, in the plain style of the MNIST README, for readers who aren't technical:
1. One line: hides faces under a solid block and removes location data, on your phone, without uploading anything.
2. What it does: finds faces → covers each with a solid block → you check every face and add or remove blocks → saves a new copy with no location, camera or other metadata.
3. Why a block and not blur: two sentences with the replication's numbers and DOI; McPherson et al. found the same pattern on faces.
4. How to use it on a phone (open the link, switch on airplane mode, pick photos, check every face, save or share) and how to run your own copy (`npm ci`, `npm run dev`, or the release zip on any static server).
5. What it never does with your photos. Each line becomes one test: never uploads them (check with airplane mode); never stores them; no ads, analytics, cookies or requests to other sites; never changes your original.
6. What it can't do: it misses some faces (numbers added at v1.0, placeholders until then), so check every photo; it doesn't hide tattoos, clothes, rooms, reflections or other people; your original, with your face and location, stays in your gallery and cloud backup; nothing can recall a photo once it has been shared.
7. Where to get help (check every link when writing): StopNCII.org (intimate images taken when you were 18 or older; the hash is made on your device); Take It Down by NCMEC (under 18 when the image was taken); India: cybercrime.gov.in and helpline 1930; the UK Revenge Porn Helpline and the US CCRI helpline once checked.

Also at M0:
- `docs/threat-model.md`: three adversaries (someone holding the leaked photo, someone running a reverse image search on it, a model trying to undo the mask). For each: what the tool protects, what it doesn't, and the check that measures it (below). Out of scope: the original on the phone or in a cloud backup, a compromised phone or browser, camera sensor fingerprints (PRNU), recognition from body and context (Oh et al.).
- `docs/eval-protocol.md`, fixed before any run: the protected-face definition, the size, angle and light bins, the bake-off rule, the speed target (agreed: median ≤ 2 s per 12 MP photo after the first, on the slowest phone) and the CI method.
- `docs/contracts.md`, `CLAUDE.md`, `docs/ai-use.md`, and the first email of the correspondence below (I draft; you send).

## Your half: evidence and paper

1. **Test set** (`eval/manifest/`): Open Images V7 validation and test images with "Human face" boxes. Annotations are CC BY 4.0 and images are listed as CC BY 2.0; store each image's licence and author from Open Images' metadata. Drop images with group-of face boxes; keep the occluded, truncated and depiction flags; check the Rotation column and the box coordinates on a few images first. Look at every sampled image and drop anything intimate or doubtful, and any image with an unboxed face. Aim for about 1,000 images and 2,000 faces; freeze with SHA-256s.
2. **Runner** (`eval/run_detect`): Playwright drives headless Chromium on a small eval page that imports the app's `detect.ts`, so decoding, preprocessing and inference are the shipped code. Until your teammate's module lands (M1), build against a stub.
3. **Scoring** (`eval/score.py`): a face is protected when masks cover ≥ 90% of its box (also report 100%, and IoU ≥ 0.5 for comparison with the literature), computed on rasterised masks so rotated boxes work. Padding and score threshold are applied here, so sweeping them needs no rerun. Report miss rate with image-level bootstrap 95% CIs and false masks per image.
4. **Honest limits**, each with numbers and CIs:
   - Missed faces by face height in pixels and by occlusion, for one 640-px pass versus tiling (this is the recall-versus-seconds trade-off).
   - Odd angles: in-plane rotation (synthetic, 0–180°); yaw (frontal / three-quarter / profile) labelled independently by both of you on about 600 faces, with Cohen's κ.
   - Low light: synthetic darkening (−1 to −4 EV with sensor-like noise), the darkest tenth of faces by luminance, and about 40 low-light photos of the two of you with lux noted.
5. **Bake-off** (M2): YuNet versus YOLO5Face-n on the same set and settings, decided by the rule fixed in the protocol (most protected faces within the speed target). If YOLO5Face-n wins, relicense to GPL-3.0 before the model is served.
6. **Threat-model checks**:
   - Leaked photo: exiftool on outputs made from your own GPS-tagged phone photos taken somewhere public (GPS, device, times, MakerNotes, XMP, C2PA, EXIF thumbnail, file name). Don't commit the originals.
   - Reverse image search: PDQ (Meta's perceptual hash, which StopNCII uses) and pHash distance from each masked output to its original; report how many still match at the recommended threshold. Optional: Google Lens and TinEye on your own photos only.
   - Undoing the mask: the masked pixels are constant, so anything a model "restores" is invented from the surrounding context. Cite your paper, McPherson et al., Hill et al. and Oh et al., with your teammate's pixel tests as the evidence.
7. **Paper**: lead author; every section except Design & Implementation and Speed; figures; `paper_numbers.py`.

## Teammate's half: app, tests, bench, demo

1. **App** (`app/`): Vite + TypeScript without a framework; installable PWA that works offline after the first load; hosted on GitHub Pages. CSP meta tag `default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; img-src 'self' blob: data:; connect-src 'self'`; the model is self-hosted.
2. **Pipeline**: `<input type="file" accept="image/*" multiple>` → `createImageBitmap(file, {imageOrientation: "from-image"})` for upright pixels → detect with ONNX Runtime Web (WASM; WebGPU where present) → padded opaque rectangles → review screen (tap a block to remove it, drag to add one, pinch to zoom) → re-encode from the canvas as JPEG → Web Share with files, or a download, under a generic file name.
3. **Phone pitfalls**: the iOS canvas limit of about 16.7 MP (downscale 48 MP photos and say so); HEIC (iOS usually hands the page a JPEG; desktop Chrome and Firefox can't decode HEIC, so show a clear message); all 8 EXIF orientations.
4. **Privacy suite** (`tests/privacy/`, Playwright on Chromium, WebKit and Firefox, run in CI), one test per README promise:
   - no requests after load while processing, and processing still works with the browser offline;
   - no image data in localStorage, IndexedDB or the Cache API afterwards;
   - the saved file has no EXIF, XMP, IPTC, C2PA or thumbnail, and no bytes after the JPEG end marker or PNG IEND (the aCropalypse bugs, CVE-2023-21036 and CVE-2023-28303);
   - decoded mask pixels equal the mask colour (exact in PNG; within ±2 in JPEG blocks inside the mask), and each block covers its padded box.
5. **Bench page** (`app/bench.html`): about 20 openly licensed ~12 MP photos from Wikimedia Commons (manifest + download script), plus "load a model file" so YOLO5Face-s, Ente's model, can be timed without ever being served. Per-stage times; first photo versus later ones; single-threaded WASM versus threaded (threads need cross-origin isolation, which GitHub Pages can't give by header, so try the service-worker workaround) versus WebGPU. Native baseline: the same ONNX files in ONNX Runtime on each laptop.
6. **Speed runs** (both of you): every phone you have, a borrowed low-end Android if possible, and both laptops; airplane mode, at least three repeats, cool-down between runs, conditions logged.
7. **Demo** (two minutes, phone screen recording, your own photos only; script in `docs/demo-script.md`): 0:00 the problem in one sentence · 0:10 airplane mode on · 0:20 pick three photos, blocks appear · 0:45 add a block over a missed face, remove a false one · 1:05 save, metadata before and after · 1:25 why a block and not blur (paper figure) · 1:45 limits, where to get help, link.
8. **Paper**: the Design & Implementation and Speed sections.

## Correspondence (you)

- A personal communication is cited only after its source has approved the exact wording in writing (`CLAUDE.md`, rule 8). Drafts and replies stay in `private/`, which git ignores.
- At M4: send the speed results and the paragraph that cites the communication, for approval.
- If the source declines or doesn't reply, drop the citation and motivate the speed test from Ente's public help pages (cite the exact page and access date).
- I draft the emails; you send them.

## Paper outline (IEEE, about 6 pages)

I Introduction · II Background and related work: McPherson; Mahloujifar; Hill; Li; Oh; your replication; existing tools (Signal's blur, ObscuraCam, Image Scrubber); on-device detectors (BlazeFace, YuNet, YOLO5Face); Ente · III Threat model · IV Design and implementation (teammate) · V Evaluation: data and protocol, missed faces, privacy checks, speed (teammate) · VI Limitations · VII Ethics and data · VIII Conclusion and availability · Acknowledgment (personal communications, if approved; AI use) · References. Before M4, each of you has your Claude review the other's sections.

## Kickoff prompts (paste into each Claude Code after M0)

Teammate:
> Read CLAUDE.md, README.md, docs/plan.md and docs/contracts.md. You own app/ and tests/. First turn every "never" line in README.md into a failing Playwright test in tests/privacy/. Then build the walking skeleton: pick one photo, detect with YuNet at 640 px, draw padded opaque blocks, save a JPEG with no metadata, deploy to GitHub Pages. One PR per step.

You:
> Read CLAUDE.md, docs/plan.md, docs/eval-protocol.md and docs/contracts.md. You own eval/ and paper/. Build the Open Images face manifest (licence, author and SHA-256 per image), the download script, and score.py with tests on synthetic boxes; then the Playwright runner against a stub of detect.ts. One PR per step.

## Verification

- CI: unit tests and the privacy suite pass on all three browser engines.
- By hand on every phone: an airplane-mode run; exiftool on saved files; rotated, HEIC and 48 MP photos.
- Reproducibility: the other person reruns the eval from the manifest and gets byte-identical detection files (hashes recorded, as in `run_info.json`).
- Paper: every number traced to `paper_numbers.txt`; help links checked; licences and attributions present.

## Right after approval, in this session

`git init` this folder, copy this plan to `docs/plan.md`, and write the M0 drafts for you to review: README.md, CLAUDE.md, docs/threat-model.md, docs/eval-protocol.md, docs/contracts.md, docs/ai-use.md, and the first email. Creating the GitHub repo, inviting your teammate and sending the email stay with you (or tell me to use `gh`).
