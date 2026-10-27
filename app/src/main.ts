import { DETECTION } from './config.ts';
import { decode } from './pipeline/decode.ts';
import { detectFaces, loadDetector } from './pipeline/detect.ts';

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

/** Shows the photo at full size; CSS scales it to the screen. */
function show(image: ImageBitmap): void {
  canvas.width = image.width;
  canvas.height = image.height;
  const context = canvas.getContext('2d');
  if (!context) throw new Error('no 2D canvas');
  context.drawImage(image, 0, 0);
  canvas.hidden = false;
}

async function open(photo: File): Promise<void> {
  choose.disabled = true;
  say('Looking for faces…');
  try {
    const image = await decode(photo);
    let found: number;
    try {
      found = (await detectFaces(image, DETECTION)).length;
      show(image);
    } finally {
      image.close();
    }
    say(found === 1 ? 'Found 1 face.' : `Found ${found} faces.`);
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
