/**
 * Decodes a photo into upright pixels: the browser applies the EXIF orientation, so every later
 * step, and every box, works on the picture as the person sees it (docs/contracts.md, section 1).
 */
export function decode(file: Blob): Promise<ImageBitmap> {
  return createImageBitmap(file, { imageOrientation: 'from-image' });
}
