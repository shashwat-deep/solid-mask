import type { DetectOptions } from './pipeline/detect.ts';

/**
 * How the app looks for faces: one pass with the long side at 640 px. The score threshold is
 * provisional: the evaluation sets it on the tune split (docs/eval-protocol.md, part B,
 * "Operating point"), and it replaces this value. 0.3 is OpenCV's NMS default for YuNet.
 */
export const DETECTION: DetectOptions = {
  model: 'yunet',
  inputSize: 640,
  tiling: { kind: 'none' },
  scoreThreshold: 0.5,
  nmsIoU: 0.3,
};

/**
 * How far each block reaches beyond the detected box, as a share of the box's width (left and
 * right) and height (top and bottom). Provisional, like the score threshold: the evaluation sets
 * it on the tune split (docs/eval-protocol.md, part B).
 */
export const PAD = 0.2;
