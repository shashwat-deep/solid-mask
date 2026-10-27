# solid-mask

Hide the faces in your photos under solid blocks and remove the hidden location data, on your own phone, without uploading anything.

> This README was written before any code, to fix what the tool must do and must never do. Numbers marked *(v1.0)* will be added when testing is finished, and the web address below is not live yet.

## What it does

1. You pick one or more photos.
2. It finds the faces and covers each one with a solid block.
3. You look over every photo. Tap a block to remove it, or drag across a face it missed to add one.
4. It saves a new copy without the hidden data that photo files carry: where and when the photo was taken, which phone took it, and its settings. Your original photo is not changed.

All of this happens inside your browser, on your phone or computer. Nothing leaves your device unless you choose to share the new copy.

## Why a solid block and not blur

Blurred and pixelated faces look hidden to people, but computers can often still recognise them. McPherson, Shokri and Shmatikov showed this in 2016. On faces blurred by YouTube's face-blurring tool, their network named the right person 57.75% of the time, choosing among 40 people, where guessing would get 2.5%.

In a replication by one of us, a small network trained on heavily blurred handwritten digits still read 89% of them, and 95% with longer training. Trained on digits pixelated down to four squares each, it read 51%, where guessing gets 10%. Against a solid block it did no better than always guessing the most common digit (11%), because nothing of the digit was left.

- R. McPherson, R. Shokri and V. Shmatikov, "Defeating image obfuscation with deep learning," arXiv:1609.00408, 2016.
- S. Deep, "Can a small convolutional network still read blurred and pixelated digits? A replication of McPherson et al. (2016)," Zenodo, 2026, [doi:10.5281/zenodo.23692156](https://doi.org/10.5281/zenodo.23692156).

## How to use it on a phone

1. Open https://shashwat-deep.github.io/solid-mask/ (not live yet).
2. Once the page has loaded, you can switch on airplane mode. The tool keeps working, which shows that it sends nothing anywhere.
3. Tap **Choose photos** and pick one or more.
4. Check every photo before you save it. Look for faces in the background, in mirrors, on screens and on posters, and add a block over any it missed.
5. Tap **Save** to keep the new copy, or **Share** to send it to another app. Your original stays in your gallery unchanged.

You can add the page to your home screen. After the first visit it works without a connection.

## Run your own copy

If you would rather not rely on our hosting, you can run the same code yourself. You need Git and Node.js:

```bash
git clone https://github.com/shashwat-deep/solid-mask.git
cd solid-mask/app
npm ci
npm run dev
```

Each release will also have a ready-built zip. Unzip it and serve the folder with any static web server, for example `python3 -m http.server`. Opening `index.html` straight from your disk won't work, because browsers don't let pages opened that way load the face detector.

## What it never does with your photos

An automated test in `tests/privacy/` will check each of these promises every time the code changes.

- It never uploads your photos. Once the page has loaded, it makes no network requests at all. You can check this with airplane mode, as above.
- It never keeps your photos. They stay in memory while you work and are gone when you close the page. Nothing from them is written to the browser's storage.
- It never tracks you. There are no accounts, ads, analytics, cookies or trackers, and nothing is loaded from any other website, not even fonts.
- It never changes your original. It saves a new file with a plain name such as `masked-1.jpg`.
- It never leaves the face in the saved file. The block replaces the face's pixels before the new file is written, so there is nothing underneath to uncover. The new file carries no hidden preview of the original and no leftover data from it.

## What it can't do

- It misses some faces. Small faces in the background, faces turned to the side and faces in poor light are the hardest. In our tests it missed *(v1.0)* of all faces, *(v1.0)* of faces seen in profile and *(v1.0)* of faces in low light. Check every photo before you share it.
- It only hides faces. Tattoos, birthmarks, hair, clothes, jewellery, your room, the view from a window, reflections in mirrors or glasses, and other people in the photo can all still identify you. Crop or cover them yourself.
- It removes the location data, but the picture itself can still show where it was taken, through a street, a landmark or a view.
- If the uncovered photo is online anywhere, a reverse image search may still match your covered copy to it. In our tests *(v1.0)* of covered copies still matched their originals.
- Your original is still on your phone. The uncovered photo, with its location data, stays in your gallery and in any cloud backup such as Google Photos or iCloud.
- It can't take a photo back. Once a photo has been sent or posted, you can't control the copies.

## About this project

The paper *(v1.0)* describes the design, the threat model and every measured limit. The threat model is in [`docs/threat-model.md`](docs/threat-model.md), and the test protocol, fixed before testing began, is in [`docs/eval-protocol.md`](docs/eval-protocol.md).

A small face-detection model runs in your browser with ONNX Runtime Web. Which model ships will be decided by testing *(v1.0)*.

The authors are Shashwat Deep and Pratyush. Claude (Anthropic), an AI assistant, helped plan the project and draft this README; [`docs/ai-use.md`](docs/ai-use.md) records what it did and what we checked.

The code is under the MIT licence ([`LICENSE`](LICENSE)), and the paper and documentation are under CC BY 4.0. If testing picks a face detector that is licensed under GPL-3.0, the code will move to GPL-3.0 before that model is used.

We are two students who built a small tool, so we can't help with individual cases. The services below can.

## Where to get help

If someone has shared photos of you without your consent, or is threatening to:

- [StopNCII.org](https://stopncii.org/), for intimate images of you taken when you were 18 or older. It makes a digital fingerprint of each image on your own device, without uploading the image, and the companies that take part use the fingerprint to find and remove copies.
- [Take It Down](https://takeitdown.ncmec.org/), from the US National Center for Missing & Exploited Children, for nude or sexual images or videos taken when you were under 18. It also makes the fingerprint on your device.
- India: report it on the [National Cyber Crime Reporting Portal](https://cybercrime.gov.in/) or call the cyber crime helpline on 1930, free and open at any hour. In an emergency, call 112.
- United Kingdom: the [Revenge Porn Helpline](https://revengepornhelpline.org.uk/), for adults, on 0345 6000 459, Monday to Friday, 10:00 to 16:00.
- United States: the [Cyber Civil Rights Initiative](https://cybercivilrights.org/) Image Abuse Helpline, on 1-844-878-2274, free and open at any hour.

If you are in danger right now, call your local emergency number.
