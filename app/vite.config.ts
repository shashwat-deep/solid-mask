import { defineConfig } from 'vite';

export default defineConfig({
  // Relative URLs, so the same build works on GitHub Pages under /solid-mask/, on any static
  // server, and unzipped from a release.
  base: './',
  build: {
    target: 'es2022',
  },
  server: {
    // eval/run_detect.py expects the eval page at http://localhost:5173/eval.html. If the port is taken,
    // fail rather than move, so a run can't reach some other server on 5173.
    port: 5173,
    strictPort: true,
  },
});
