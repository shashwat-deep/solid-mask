/**
 * The face detector the app ships: face_detection_yunet_2023mar.onnx from the OpenCV Zoo, MIT
 * licence (docs/eval-protocol.md, part C). Model files are never committed (CLAUDE.md, rule 4):
 * scripts/fetch-model.ts downloads this one and checks its SHA-256.
 */
export const YUNET = {
  file: 'face_detection_yunet_2023mar.onnx',
  sha256: '8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4',
  /** The model's input is fixed at 1 x 3 x 640 x 640. */
  inputSize: 640,
} as const;
