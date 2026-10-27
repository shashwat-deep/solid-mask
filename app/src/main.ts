import { DETECTION, PAD } from './config.ts';
import { decode } from './pipeline/decode.ts';
import { detectFaces, loadDetector } from './pipeline/detect.ts';
import { drawMasks, maskFor, type Rect } from './pipeline/mask.ts';

function element<T extends HTMLElement>(id: string): T {
  const found = document.getElementById(id);
  if (!found) throw new Error(`#${id} is missing from index.html`);
  return found as T;
}

const choose = element<HTMLButtonElement>('choose');
const file = element<HTMLInputElement>('file');
const status = element<HTMLParagraphElement>('status');
const canvas = element<HTMLCanvasElement>('photo');

function say(message: string): void {
  status.textContent = message;
}

/**
 * Draws the photo at full size with its blocks painted over it, in one go, so the uncovered photo
 * is never on screen. CSS scales the canvas to the screen.
 */
function show(image: ImageBitmap, masks: Rect[]): void {
  canvas.width = image.width;
  canvas.height = image.height;
  const context = canvas.getContext('2d');
  if (!context) throw new Error('no 2D canvas');
  context.drawImage(image, 0, 0);
  drawMasks(context, masks);
  canvas.hidden = false;
}

/** What to tell the person once the blocks are painted. Finding no face must not read like success. */
function coverage(faces: number): string {
  if (faces === 0) return 'No faces found, so nothing is covered. Check the whole photo.';
  return `${faces === 1 ? 'Covered 1 face.' : `Covered ${faces} faces.`} Check the whole photo for faces it missed.`;
}

async function open(photo: File): Promise<void> {
  choose.disabled = true;
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
    say(coverage(masks.length));
  } catch (error) {
    console.error(error);
    canvas.hidden = true;
    say("This photo couldn't be opened. Try a JPEG or PNG photo.");
  } finally {
    choose.disabled = false;
  }
}

choose.addEventListener('click', () => file.click());
file.addEventListener('change', () => {
  const photo = file.files?.[0];
  // Clear the input, so choosing the same photo again still counts as a change.
  file.value = '';
  if (photo) void open(photo);
});

// Everything the app needs is loaded before it says it is ready; after that it works offline.
loadDetector().then(
  () => {
    say('Ready. You can switch on airplane mode now: nothing else needs to load.');
    choose.disabled = false;
  },
  (error: unknown) => {
    console.error(error);
    say("The face finder couldn't load. Check your connection, then reload the page.");
  },
);
