# CLAUDE.md

Two people build this project, each with their own Claude Code session, and both sessions read this file. Its rules come before any other habit.

## Project

solid-mask is a phone-first web app that covers faces with solid blocks and strips metadata, entirely inside the browser, together with a software paper in IEEE format, released on Zenodo. The full plan, with milestones M0 to M5, is in `docs/plan.md`. It was written for Shashwat: there, "you" is Shashwat and "your teammate" is Pratyush.

## Who owns what

| Area | Owner | Folders and files |
|---|---|---|
| Evidence and paper | Shashwat Deep (@shashwat-deep) | `eval/`, `paper/`, `docs/threat-model.md`, `docs/eval-protocol.md` |
| App, tests, bench page, demo | Pratyush (@06pratyush) | `app/`, `tests/`, `docs/demo-script.md` |
| Shared | both | `README.md`, `CLAUDE.md`, `docs/contracts.md`, `docs/plan.md`, `docs/ai-use.md`, `results/` |

If you don't know whose session you are in, ask. Don't edit the other person's folders; open an issue or comment on their PR instead. Every PR is approved by the other person (`.github/CODEOWNERS`).

## Rules

1. No app code until M0 is merged: `README.md`, this file, `docs/threat-model.md`, `docs/eval-protocol.md` and `docs/contracts.md`, approved by both.
2. Privacy invariants, from the README's "What it never does with your photos":
   - no network request after the page has loaded;
   - nothing from a photo in localStorage, sessionStorage, IndexedDB, the Cache API or cookies;
   - no third-party scripts, fonts, CDNs, analytics or trackers; every asset, the model included, is served from our own origin;
   - the block is drawn opaque into the pixel buffer before encoding, and the saved file is encoded fresh from that buffer.

   If a change could break any of these, stop and ask the human.
3. Data: test only on openly licensed, non-intimate images. Never commit test images; commit a manifest (ID, URL, licence, author, SHA-256) and a script that downloads and checks them. Figures and the demo show only the two authors. Photos carrying real GPS data are never committed.
4. Licences: never copy code from Ente (AGPL-3.0) or yolov5-face (GPL-3.0), not even with changes; reading and citing them is fine. Never commit or serve YOLO5Face weights unless the bake-off picks YOLO5Face and the code has moved to GPL-3.0. `.gitignore` blocks every `.onnx`, `.pt` and `.pth` file; committing a model needs an explicit exception there, in a PR both approve. Runtime dependencies must be MIT, BSD or Apache-2.0; check before adding one. ISC, and MPL-2.0 for unmodified third-party code inside a shipped binary are also allowed.
5. Numbers: every number in the paper or the README comes from committed script output (`eval/paper_numbers.py` → `paper_numbers.txt`). Each run records software versions, model SHA-256s and data hashes, as `run_info.json` did in the MNIST repo.
6. Interfaces are defined in `docs/contracts.md`. Changing one needs both people's approval and a version bump there.
7. Log AI use in `docs/ai-use.md` (date, who, what Claude did, what the person checked) whenever Claude writes something that ends up in the repo, the paper or an email.
8. Personal communications: never quote or paraphrase anyone's private remarks in the repo, the paper or an issue until they have approved the exact wording in writing. Drafts and replies stay in `private/`, which git ignores.

## Working style

- Small PRs, one step each; never push to `main`. Run `/code-review` on your own PR before asking the other person to review it.
- Write plainly and exactly, in the style of https://github.com/shashwat-deep/mnist-obfuscation-replication (its README and paper): exact numbers with their confidence intervals, no marketing words.
- The README is for people who aren't technical: short sentences, everyday words.

## Commands

App (`app/`):

```bash
cd app
npm ci
npm run dev         # development server
npm run build       # type-checks, then writes the site to app/dist
npm run preview     # serves app/dist
```

`dev` and `build` first run `npm run fetch-model`, which downloads the YuNet model into `app/models/` and checks its SHA-256 (models are never committed).

Unit tests and privacy suite (`tests/`, see `tests/README.md`):

```bash
cd tests
npm ci
npx playwright install --with-deps chromium firefox webkit
npm test            # builds app/, runs the unit tests, then the privacy suite in Chromium, Firefox and WebKit
npm run test:unit   # unit tests only (Vitest, no browser)
npm run typecheck
```

CI (`.github/workflows/pages.yml`) runs `npm test` in `tests/` on every pull request and push to `main`; on `main` it then deploys the tested `app/dist` to GitHub Pages.

Eval, from the top folder (`eval/README.md` explains each step):

```bash
uv venv --python 3.13 .venv && uv pip sync --python .venv/bin/python eval/requirements.txt   # once
.venv/bin/python -m playwright install --only-shell chromium     # once, for the runner
.venv/bin/python -m pytest eval/tests                            # tests
.venv/bin/python eval/download.py                                # test images into data/, checked against their SHA-256s
.venv/bin/python eval/review_sheet.py                            # page for reviewing the images not yet reviewed
.venv/bin/python eval/build_manifest.py                          # redraw the test set after a round of the review
.venv/bin/python eval/run_detect.py --page URL                   # detections into results/detections/ (--page stub: data/stub-runs/)
.venv/bin/python eval/score.py RUN.jsonl --operating-point       # pad and threshold, on the tune split
.venv/bin/python eval/score.py RUN.jsonl --pad P --threshold T   # score the report split
```
