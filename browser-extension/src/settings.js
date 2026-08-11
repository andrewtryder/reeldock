// Default settings used on first install and as the in-memory state seed.
export const DEFAULT_SETTINGS = Object.freeze({
  serverUrl: '',
  apiToken: '',
  defaultDestinationFolder: '',
  triggerAbsScan: false,
  embedMetadata: true,
  embedThumbnail: true,
  embedChapters: true,
  allowReimport: false,
});

// Storage keys we persist. Keep this list in sync with options.js.
export const STORAGE_KEYS = [
  'serverUrl',
  'apiToken',
  'defaultDestinationFolder',
  'triggerAbsScan',
  'embedMetadata',
  'embedThumbnail',
  'embedChapters',
  'allowReimport',
];

export const HTTPS_REQUIRED_ERROR =
  'HTTPS is required for ReelDock servers other than localhost.';

const LOOPBACK_HOSTS = new Set(['localhost', '127.0.0.1', '::1']);

function stripIpv6Brackets(hostname) {
  return hostname.replace(/^\[|\]$/g, '').toLowerCase();
}

export function isLoopbackHostname(hostname) {
  if (!hostname) return false;
  return LOOPBACK_HOSTS.has(stripIpv6Brackets(hostname));
}

/** True when the configured server is loopback (localhost / 127.0.0.1 / ::1). */
export function isLocalServerUrl(serverUrl) {
  if (!serverUrl) return false;
  try {
    return isLoopbackHostname(new URL(serverUrl).hostname);
  } catch {
    return false;
  }
}

/**
 * Normalize a user-entered ReelDock server address to an origin.
 * Rejects non-loopback HTTP so the API token is never sent over plaintext
 * to a remote host.
 *
 * @returns {{ ok: true, origin: string, error: '' } | { ok: false, origin: '', error: string }}
 */
export function normalizeAndValidateServerUrl(input) {
  if (typeof input !== 'string' || !input.trim()) {
    return { ok: false, origin: '', error: 'Enter a ReelDock server URL.' };
  }

  let parsed;
  try {
    parsed = new URL(input.trim());
  } catch {
    return { ok: false, origin: '', error: 'Enter a valid ReelDock server URL.' };
  }

  const scheme = parsed.protocol.toLowerCase();
  if (scheme !== 'http:' && scheme !== 'https:') {
    return { ok: false, origin: '', error: 'Server URL must use http:// or https://.' };
  }

  if (parsed.username || parsed.password) {
    return {
      ok: false,
      origin: '',
      error: 'Server URL must not include a username or password.',
    };
  }

  if (parsed.search || parsed.hash) {
    return {
      ok: false,
      origin: '',
      error: 'Server URL must not include a query string or fragment.',
    };
  }

  const path = parsed.pathname;
  if (path && path !== '/') {
    return {
      ok: false,
      origin: '',
      error: 'Server URL must be an origin only (no path).',
    };
  }

  if (scheme === 'http:' && !isLoopbackHostname(parsed.hostname)) {
    return { ok: false, origin: '', error: HTTPS_REQUIRED_ERROR };
  }

  return { ok: true, origin: parsed.origin, error: '' };
}

export function requireValidatedServerOrigin(input) {
  const result = normalizeAndValidateServerUrl(input);
  if (!result.ok) {
    throw new Error(result.error);
  }
  return result.origin;
}

/** Optional host-permission pattern for a validated origin. */
export function optionalHostPermissionPattern(origin) {
  return `${origin}/*`;
}

/** Request optional host permission for non-loopback ReelDock origins. */
export async function ensureServerHostPermission(serverUrl) {
  const origin = requireValidatedServerOrigin(serverUrl);
  if (isLocalServerUrl(origin)) {
    return true;
  }
  const originPattern = optionalHostPermissionPattern(origin);
  const already = await chrome.permissions.contains({ origins: [originPattern] });
  if (already) {
    return true;
  }
  return chrome.permissions.request({ origins: [originPattern] });
}

// Load settings from storage, filling in defaults for missing keys.
// Valid server URLs are rewritten to the normalized origin.
export async function loadSettings() {
  const result = await chrome.storage.local.get(STORAGE_KEYS);
  const settings = { ...DEFAULT_SETTINGS, ...result };
  if (settings.serverUrl) {
    const validated = normalizeAndValidateServerUrl(settings.serverUrl);
    if (validated.ok && validated.origin !== settings.serverUrl) {
      settings.serverUrl = validated.origin;
      await chrome.storage.local.set({ serverUrl: validated.origin });
    }
  }
  return settings;
}

// Save a settings object to storage. serverUrl is stored as a validated origin.
export async function saveSettings(settings) {
  const payload = {};
  for (const key of STORAGE_KEYS) {
    if (key in settings) payload[key] = settings[key];
  }
  if (payload.serverUrl) {
    payload.serverUrl = requireValidatedServerOrigin(payload.serverUrl);
  }
  await chrome.storage.local.set(payload);
  return payload;
}

// Return true if the URL points to a single YouTube video.
// Matches youtube.com/watch?v=ID and youtu.be/ID (11-12 char IDs).
export function isYouTubeWatchUrl(url) {
  if (!url) return false;
  let parsed;
  try {
    parsed = new URL(url);
  } catch {
    return false;
  }
  const host = parsed.hostname.toLowerCase();
  if (host === 'youtu.be') {
    return /^\/[\w-]{11,12}$/.test(parsed.pathname);
  }
  if (host === 'www.youtube.com' || host === 'youtube.com' || host === 'm.youtube.com') {
    if (parsed.pathname === '/watch') {
      return /^[A-Za-z0-9_-]{11,12}$/.test(parsed.searchParams.get('v') || '');
    }
    // youtu.be short links can also appear as /shorts/ID
    if (parsed.pathname.startsWith('/shorts/')) {
      return /^\/shorts\/[\w-]{11,12}$/.test(parsed.pathname);
    }
  }
  return false;
}
