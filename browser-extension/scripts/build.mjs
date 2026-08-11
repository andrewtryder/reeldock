// Builds unpacked extensions for Chrome and Firefox into dist/<browser>/.
// Copies src/* + icons/, then writes the per-browser manifest at the root.

import { cp, mkdir, readdir, readFile, rm, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import process from 'node:process';

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(__dirname, '..');
const TARGETS = ['chrome', 'firefox'];

async function build(target) {
  const dist = resolve(ROOT, 'dist', target);
  await rm(dist, { recursive: true, force: true });
  await mkdir(dist, { recursive: true });

  // Copy the icons directory (referenced by manifest + notifications API).
  await cp(resolve(ROOT, 'icons'), resolve(dist, 'icons'), { recursive: true });

  // Copy every runtime source file the unpacked extension needs.
  const srcDir = resolve(ROOT, 'src');
  for (const name of await readdir(srcDir)) {
    if (!/\.(js|html)$/.test(name)) continue;
    await cp(resolve(srcDir, name), resolve(dist, name));
  }

  // Merge the per-browser manifest with the shared base and write it to the dist root.
  const base = JSON.parse(await readFile(resolve(ROOT, 'manifests', 'base.json'), 'utf8'));
  const overrides = JSON.parse(await readFile(resolve(ROOT, 'manifests', `${target}.json`), 'utf8'));
  const manifest = { ...base, ...overrides };
  // Firefox uses background.scripts; Chrome uses background.service_worker.
  if (target === 'chrome') {
    delete manifest.background?.scripts;
  } else if (target === 'firefox') {
    delete manifest.background?.service_worker;
  }
  await writeFile(resolve(dist, 'manifest.json'), JSON.stringify(manifest, null, 2) + '\n', 'utf8');

  console.log(`Built ${target} -> dist/${target}/`);
}

const requested = process.argv.slice(2).filter((a) => TARGETS.includes(a));
const targets = requested.length ? requested : TARGETS;
for (const t of targets) await build(t);
