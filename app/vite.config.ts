import { defineConfig } from 'vite';

export default defineConfig({
  // Relative URLs, so the same build works on GitHub Pages under /solid-mask/, on any static
  // server, and unzipped from a release.
  base: './',
  build: {
    target: 'es2022',
  },
});
