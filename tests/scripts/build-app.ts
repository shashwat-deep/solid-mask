// Builds app/ before the suite runs, so the tests always see the current code.
// Until app/ exists there is nothing to build, and every privacy test fails.
import { spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const app = fileURLToPath(new URL('../../app/', import.meta.url));

if (!existsSync(`${app}package.json`)) {
  console.log('tests: there is no app/ to build yet, so every privacy test will fail.');
} else if (!existsSync(`${app}node_modules`)) {
  console.error('tests: run `npm ci` in app/ first.');
  process.exitCode = 1;
} else {
  process.exitCode = spawnSync('npm run build', { cwd: app, stdio: 'inherit', shell: true }).status ?? 1;
}
