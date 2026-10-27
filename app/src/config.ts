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
