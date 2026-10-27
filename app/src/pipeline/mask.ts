import type { Box } from './detect.ts';

/** A rectangle in whole pixels of the upright image. */
export type Rect = { x: number; y: number; w: number; h: number };

/** The block colour (docs/contracts.md, section 2). */
export const BLOCK_COLOUR = '#000000';

/**
 * The mask for a detected box (docs/contracts.md, section 2): the box grown by pad × w on the left
 * and right and by pad × h at the top and bottom, clipped to the image, then widened to whole
 * pixels so that no pixel at its edge is only partly covered.
 */
export function maskFor(box: Box, pad: number, width: number, height: number): Rect {
  const left = Math.max(0, Math.floor(box.x - pad * box.w));
  const top = Math.max(0, Math.floor(box.y - pad * box.h));
  const right = Math.min(width, Math.ceil(box.x + box.w + pad * box.w));
  const bottom = Math.min(height, Math.ceil(box.y + box.h + pad * box.h));
  return { x: left, y: top, w: Math.max(0, right - left), h: Math.max(0, bottom - top) };
}

/**
 * Paints each mask into the canvas's pixels as an opaque rectangle of the block colour. The saved
 * file is encoded from these pixels, so nothing of the face is left under a block.
 */
export function drawMasks(context: CanvasRenderingContext2D, masks: Rect[]): void {
  context.save();
  context.setTransform(1, 0, 0, 1, 0, 0);
  context.globalAlpha = 1;
  context.globalCompositeOperation = 'source-over';
  context.fillStyle = BLOCK_COLOUR;
  for (const m of masks) context.fillRect(m.x, m.y, m.w, m.h);
  context.restore();
}
