// Default settings used on first install and as the in-memory state seed.
export const DEFAULT_SETTINGS = Object.freeze({
  serverUrl: '',
  authEnabled: true,
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
  'authEnabled',
  'apiToken',
  'defaultDestinationFolder',
  'triggerAbsScan',
  'embedMetadata',
  'embedThumbnail',
  'embedChapters',
  'allowReimport',
];

export function isLocalServerUrl(serverUrl) {
  if (!serverUrl) return false;
  try {
    const parsed = new URL(serverUrl);
    return parsed.hostname === 'localhost' || parsed.hostname === '127.0.0.1';
  } catch {
    return false;
  }
}

/** Request optional host permission for non-localhost ReelDock origins. */
export async function ensureServerHostPermission(serverUrl) {
  if (!serverUrl || isLocalServerUrl(serverUrl)) {
    return true;
  }
  const parsed = new URL(serverUrl);
  const originPattern = `${parsed.origin}/*`;
  const already = await chrome.permissions.contains({ origins: [originPattern] });
  if (already) {
    return true;
  }
  return chrome.permissions.request({ origins: [originPattern] });
}

// Load settings from storage, filling in defaults for missing keys.
export async function loadSettings() {
  const result = await chrome.storage.local.get(STORAGE_KEYS);
  return { ...DEFAULT_SETTINGS, ...result };
}

// Save a settings object to storage.
export async function saveSettings(settings) {
  const payload = {};
  for (const key of STORAGE_KEYS) {
    if (key in settings) payload[key] = settings[key];
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
