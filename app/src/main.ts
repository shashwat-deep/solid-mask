import { DETECTION, PAD } from './config.ts';
import { decode } from './pipeline/decode.ts';
import { detectFaces, loadDetector } from './pipeline/detect.ts';
import { encodeJpeg } from './pipeline/encode.ts';
import { maskFor, paint, type Rect } from './pipeline/mask.ts';

function element<T extends HTMLElement>(id: string): T {
  const found = document.getElementById(id);
  if (!found) throw new Error(`#${id} is missing from index.html`);
  return found as T;
}

const choose = element<HTMLButtonElement>('choose');
const save = element<HTMLButtonElement>('save');
const file = element<HTMLInputElement>('file');
const status = element<HTMLParagraphElement>('status');
const canvas = element<HTMLCanvasElement>('photo');

let detectorReady = false; // the face detector has loaded and run once
let masked = false; // the canvas holds a photo with its blocks painted in
let busy = false; // a photo is being opened or saved
let saved = 0; // copies saved in this session, which number the file names

function update(): void {
  choose.disabled = busy || !detectorReady;
  save.disabled = busy || !masked;
}

function say(message: string): void {
  status.textContent = message;
}

/** Shows the photo with its blocks painted in; CSS scales the canvas to the screen. */
function show(image: ImageBitmap, masks: Rect[]): void {
  paint(canvas, image, masks);
  canvas.hidden = false;
}

/** What to tell the person once the blocks are painted. Finding no face must not read like success. */
function coverage(faces: number): string {
  if (faces === 0) return 'No faces found, so nothing is covered. Check the whole photo before you save it.';
  return `${faces === 1 ? 'Covered 1 face.' : `Covered ${faces} faces.`} Check the whole photo for faces it missed before you save it.`;
}

async function open(photo: File): Promise<void> {
  // Turn Save off at once, so the previous photo can't be saved in place of this one.
  busy = true;
  masked = false;
  update();
  say('Looking for faces…');
  try {
    const image = await decode(photo);
    let masks: Rect[];
    try {
      const faces = await detectFaces(image, DETECTION);
      masks = faces.map((face) => maskFor(face, PAD, image.width, image.height));
      show(image, masks);
    } finally {
      image.close();
    }
    masked = true;
    say(coverage(masks.length));
  } catch (error) {
    console.error(error);
    canvas.hidden = true;
    say("This photo couldn't be opened. Try a JPEG or PNG photo.");
  } finally {
    busy = false;
    update();
  }
}

/** Hands a file to the browser as a download. */
function download(blob: Blob, name: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = name;
  document.body.append(link);
  link.click();
  link.remove();
  // Long enough for the download to start; the URL never outlives the page.
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

async function saveCopy(): Promise<void> {
  busy = true;
  update();
  try {
    const copy = await encodeJpeg(canvas);
    saved += 1;
    const name = `masked-${saved}.jpg`;
    download(copy, name);
    say(`Saved a new copy as ${name}. Your original photo is unchanged.`);
  } catch (error) {
    console.error(error);
    say("The copy couldn't be saved. Try again.");
  } finally {
    busy = false;
    update();
  }
}

choose.addEventListener('click', () => file.click());
save.addEventListener('click', () => void saveCopy());
file.addEventListener('change', () => {
  const photo = file.files?.[0];
  // Clear the input, so choosing the same photo again still counts as a change.
  file.value = '';
  if (photo) void open(photo);
});

// Everything the app needs is loaded before it says it is ready; after that it works offline.
loadDetector().then(
  () => {
    detectorReady = true;
    update();
    say('Ready. You can switch on airplane mode now: nothing else needs to load.');
  },
  (error: unknown) => {
    console.error(error);
    say("The face finder couldn't load. Check your connection, then reload the page.");
  },
);
