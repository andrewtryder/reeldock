// Store-readiness checks for manifests and packaged source.
import { readdir, readFile } from 'node:fs/promises';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(__dirname, '..');

function fail(message) {
  throw new Error(message);
}

const base = JSON.parse(await readFile(resolve(ROOT, 'manifests', 'base.json'), 'utf8'));
const chromeOverride = JSON.parse(await readFile(resolve(ROOT, 'manifests', 'chrome.json'), 'utf8'));
const firefoxOverride = JSON.parse(await readFile(resolve(ROOT, 'manifests', 'firefox.json'), 'utf8'));

if (base.manifest_version !== 3) fail('manifest_version must be 3');
if (base.homepage_url !== 'https://github.com/andrewtryder/reeldock') {
  fail('homepage_url must point at the GitHub repository');
}
if (!base.content_security_policy?.extension_pages?.includes("script-src 'self'")) {
  fail('CSP must restrict extension_pages to script-src self');
}

const youtubeHosts = (base.host_permissions || []).filter((p) => /youtube|youtu\.be/i.test(p));
if (youtubeHosts.length) {
  fail(`YouTube host_permissions must be removed: ${youtubeHosts.join(', ')}`);
}

const requiredLoopback = [
  'http://localhost/*',
  'http://127.0.0.1/*',
  'http://[::1]/*',
  'https://localhost/*',
  'https://127.0.0.1/*',
  'https://[::1]/*',
];
for (const pattern of requiredLoopback) {
  if (!base.host_permissions?.includes(pattern)) {
    fail(`missing required loopback host permission: ${pattern}`);
  }
}

const optional = base.optional_host_permissions || [];
if (optional.includes('http://*/*')) {
  fail('optional_host_permissions must not include http://*/*');
}
if (JSON.stringify(optional) !== JSON.stringify(['https://*/*'])) {
  fail(`optional_host_permissions must be exactly ["https://*/*"], got ${JSON.stringify(optional)}`);
}

const gecko = firefoxOverride.browser_specific_settings?.gecko;
if (gecko?.id !== '@reeldock.andrewtryder') {
  fail(`Firefox gecko.id must be @reeldock.andrewtryder, got ${gecko?.id}`);
}
if (gecko.strict_min_version !== '140.0') {
  fail(`Firefox strict_min_version must be 140.0, got ${gecko.strict_min_version}`);
}
if (firefoxOverride.browser_specific_settings?.gecko_android) {
  fail('gecko_android must stay omitted (desktop Firefox only)');
}
const requiredTypes = gecko.data_collection_permissions?.required || [];
for (const type of ['browsingActivity', 'authenticationInfo']) {
  if (!requiredTypes.includes(type)) {
    fail(`Firefox data_collection_permissions.required must include ${type}`);
  }
}
if (requiredTypes.includes('none')) {
  fail('Firefox data_collection_permissions must not claim none');
}

const srcDir = resolve(ROOT, 'src');
const srcFiles = await readdir(srcDir);
const prohibited = [
  { re: /\beval\s*\(/, label: 'eval(' },
  { re: /\bnew\s+Function\s*\(/, label: 'new Function' },
  { re: /\.innerHTML\s*=/, label: 'innerHTML assignment' },
  { re: /\.outerHTML\s*=/, label: 'outerHTML assignment' },
  { re: /\.insertAdjacentHTML\s*\(/, label: 'insertAdjacentHTML' },
];

for (const name of srcFiles) {
  if (!/\.(js|html)$/.test(name)) continue;
  const text = await readFile(resolve(srcDir, name), 'utf8');
  if (name.endsWith('.html')) {
    if (/<script[^>]+src=["']https?:\/\//i.test(text)) {
      fail(`${name}: remote <script src> is prohibited`);
    }
  }
  if (name.endsWith('.js')) {
    if (/import\s*\(\s*['"]https?:\/\//.test(text)) {
      fail(`${name}: remote dynamic import is prohibited`);
    }
    for (const { re, label } of prohibited) {
      if (re.test(text)) fail(`${name}: ${label} is prohibited`);
    }
  }
}

// Chrome and Firefox overrides should only differ in background wiring + gecko.
const chromeKeys = Object.keys(chromeOverride).sort();
if (JSON.stringify(chromeKeys) !== JSON.stringify(['background'])) {
  fail(`chrome.json should only override background, got ${chromeKeys.join(', ')}`);
}
const firefoxKeys = Object.keys(firefoxOverride).sort();
if (JSON.stringify(firefoxKeys) !== JSON.stringify(['background', 'browser_specific_settings'])) {
  fail(`firefox.json unexpected keys: ${firefoxKeys.join(', ')}`);
}

console.log('check-store: OK');
