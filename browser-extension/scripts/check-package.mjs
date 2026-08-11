// Fail if packaged zips contain anything other than intended runtime files.
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { readFile } from 'node:fs/promises';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const run = promisify(execFile);
const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(__dirname, '..');

const ALLOWED = new Set([
  'manifest.json',
  'popup.html',
  'popup.js',
  'options.html',
  'options.js',
  'background.js',
  'settings.js',
  'ui.js',
  'browser-api.js',
  'icons/icon-16.png',
  'icons/icon-32.png',
  'icons/icon-48.png',
  'icons/icon-128.png',
  'icons/icon.svg',
]);

const FORBIDDEN_FRAGMENTS = [
  '.env',
  'node_modules',
  'tests/',
  'test/',
  '.map',
  '.git',
  'package-lock',
  'README',
  'PRIVACY',
  'store/',
];

function fail(message) {
  throw new Error(message);
}

async function listZip(zipPath) {
  const { stdout } = await run('unzip', ['-Z1', zipPath]);
  return stdout
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .filter((name) => !name.endsWith('/'));
}

const version = JSON.parse(await readFile(resolve(ROOT, 'package.json'), 'utf8')).version;
const zips = [
  resolve(ROOT, 'artifacts', `reeldock-chrome-v${version}.zip`),
  resolve(ROOT, 'artifacts', `reeldock-firefox-v${version}.zip`),
];

for (const zipPath of zips) {
  const entries = await listZip(zipPath);
  const extra = entries.filter((name) => !ALLOWED.has(name));
  const missing = [...ALLOWED].filter((name) => !entries.includes(name));
  if (extra.length) fail(`${zipPath}: unexpected files: ${extra.join(', ')}`);
  if (missing.length) fail(`${zipPath}: missing files: ${missing.join(', ')}`);
  for (const name of entries) {
    for (const fragment of FORBIDDEN_FRAGMENTS) {
      if (name.includes(fragment)) fail(`${zipPath}: forbidden path ${name}`);
    }
  }

  const { stdout } = await run('unzip', ['-p', zipPath, 'manifest.json']);
  const manifest = JSON.parse(stdout);
  if (manifest.version !== version) {
    fail(`${zipPath}: manifest version ${manifest.version} != package ${version}`);
  }
  if (/\beval\s*\(|new\s+Function\s*\(/.test(stdout)) {
    fail(`${zipPath}: manifest must not contain eval`);
  }
}

console.log(`check-package: OK (${zips.length} zips, version ${version})`);
