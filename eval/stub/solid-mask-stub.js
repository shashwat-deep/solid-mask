// A stand-in for the app's eval page (app/eval.html, docs/contracts.md, section 3), with the same interface,
// window.solidMask, so that eval/run_detect.py can be built and tested before that page exists. decode() and
// render() do what the contract asks. detectFaces() is not a face detector: it returns the bounding box of every
// connected patch of solid magenta, which the tests draw where the faces are, so the runner and eval/score.py can be
// checked end to end with known answers. A photo with no magenta gets no boxes.

const SCORE = 0.9;
const isMagenta = (data, p) => data[4 * p] > 200 && data[4 * p + 1] < 80 && data[4 * p + 2] > 200;

async function decode(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${url}: HTTP ${response.status}`);
  return createImageBitmap(await response.blob(), { imageOrientation: 'from-image' });
}

async function detectFaces(image, options) {
  const { width, height } = image;
  const context = new OffscreenCanvas(width, height).getContext('2d', { willReadFrequently: true });
  context.drawImage(image, 0, 0);
  const data = context.getImageData(0, 0, width, height).data;
  const seen = new Uint8Array(width * height);
  const boxes = [];
  for (let start = 0; start < width * height; start++) {
    if (seen[start] || !isMagenta(data, start)) continue;
    let [x0, y0, x1, y1] = [width, height, 0, 0];
    const stack = [start];
    seen[start] = 1;
    while (stack.length) {
      const p = stack.pop();
      const x = p % width;
      const y = (p - x) / width;
      [x0, y0, x1, y1] = [Math.min(x0, x), Math.min(y0, y), Math.max(x1, x + 1), Math.max(y1, y + 1)];
      const neighbours = [x > 0 ? p - 1 : -1, x < width - 1 ? p + 1 : -1, y > 0 ? p - width : -1,
                          y < height - 1 ? p + width : -1];
      for (const q of neighbours) {
        if (q >= 0 && !seen[q] && isMagenta(data, q)) {
          seen[q] = 1;
          stack.push(q);
        }
      }
    }
    boxes.push({ x: x0, y: y0, w: x1 - x0, h: y1 - y0, score: SCORE });
  }
  return boxes.filter((b) => b.score >= options.scoreThreshold);
}

async function render(image, masks) {
  const canvas = new OffscreenCanvas(image.width, image.height);
  const context = canvas.getContext('2d');
  context.drawImage(image, 0, 0);
  context.fillStyle = '#000000';
  for (const m of masks) {
    const x0 = Math.max(0, Math.floor(m.x));
    const y0 = Math.max(0, Math.floor(m.y));
    const x1 = Math.min(image.width, Math.ceil(m.x + m.w));
    const y1 = Math.min(image.height, Math.ceil(m.y + m.h));
    if (x1 > x0 && y1 > y0) context.fillRect(x0, y0, x1 - x0, y1 - y0);
  }
  return canvas.convertToBlob({ type: 'image/jpeg', quality: 0.92 });
}

function info() {
  return { ortVersion: 'none (stub)', backend: 'stub', threads: 1, modelSha256: '' };
}

window.solidMask = { decode, detectFaces, render, info };
