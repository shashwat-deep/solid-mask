import { describe, expect, it } from 'vitest';
import { BLOCK_COLOUR, drawMasks, maskFor } from '../../app/src/pipeline/mask.ts';

const box = (x: number, y: number, w: number, h: number) => ({ x, y, w, h, score: 0.9 });

describe('maskFor', () => {
  it('grows the box by pad x width on each side and pad x height at the top and bottom', () => {
    expect(maskFor(box(100, 200, 50, 80), 0.2, 1000, 1000)).toEqual({ x: 90, y: 184, w: 70, h: 112 });
  });

  it('clips the mask to the image', () => {
    // Unclipped, this mask would run from (-30, -17.5) to (90, 57.5).
    expect(maskFor(box(-10, -5, 80, 50), 0.25, 60, 40)).toEqual({ x: 0, y: 0, w: 60, h: 40 });
  });

  it('widens the mask to whole pixels, so no edge pixel is only partly covered', () => {
    expect(maskFor(box(10.4, 20.6, 5.2, 5.2), 0, 100, 100)).toEqual({ x: 10, y: 20, w: 6, h: 6 });
  });

  it('gives an empty mask for a box wholly outside the image', () => {
    const mask = maskFor(box(200, 200, 10, 10), 0.2, 100, 100);
    expect(mask.w * mask.h).toBe(0);
  });
});

describe('drawMasks', () => {
  it('fills each mask with opaque #000000, with no transform or blending, and restores the context', () => {
    const calls: unknown[][] = [];
    const state = { fillStyle: '#ff0000', globalAlpha: 0.5, globalCompositeOperation: 'multiply' };
    const context = {
      ...state,
      save: () => calls.push(['save']),
      restore: () => calls.push(['restore']),
      setTransform: (...m: number[]) => calls.push(['setTransform', ...m]),
      fillRect(x: number, y: number, w: number, h: number) {
        calls.push(['fillRect', x, y, w, h, this.fillStyle, this.globalAlpha, this.globalCompositeOperation]);
      },
    };
    drawMasks(context as unknown as CanvasRenderingContext2D, [
      { x: 1, y: 2, w: 3, h: 4 },
      { x: 5, y: 6, w: 7, h: 8 },
    ]);
    expect(BLOCK_COLOUR).toBe('#000000');
    expect(calls).toEqual([
      ['save'],
      ['setTransform', 1, 0, 0, 1, 0, 0],
      ['fillRect', 1, 2, 3, 4, '#000000', 1, 'source-over'],
      ['fillRect', 5, 6, 7, 8, '#000000', 1, 'source-over'],
      ['restore'],
    ]);
  });
});
