/** Destination dropdown helpers. Three-state: server default, library root, folder. */

export const SERVER_DEFAULT_VALUE = '';
export const LIBRARY_ROOT_VALUE = '__root__';
export const LIBRARY_ROOT_LABEL = 'Library root';

export function serverDefaultLabel(serverDefault = '') {
  const name = String(serverDefault || '').trim();
  return name ? `Server default — ${name}` : 'Server default';
}

export function destinationChoices(folders = [], serverDefault = '') {
  const names = (folders || []).filter((name) => typeof name === 'string' && name);
  return [
    { value: SERVER_DEFAULT_VALUE, label: serverDefaultLabel(serverDefault) },
    { value: LIBRARY_ROOT_VALUE, label: LIBRARY_ROOT_LABEL },
    ...names.map((name) => ({ value: name, label: name })),
  ];
}

/**
 * Resolve the selected destination when the saved default is stale.
 * Missing or "" = server default (upgrade-safe). __root__ = library root.
 */
export function resolveSavedDestination(saved, folders = [], serverDefault = '') {
  const names = folders || [];
  if (saved == null || saved === SERVER_DEFAULT_VALUE) {
    return { value: SERVER_DEFAULT_VALUE, banner: '' };
  }
  if (saved === LIBRARY_ROOT_VALUE) {
    return { value: LIBRARY_ROOT_VALUE, banner: '' };
  }
  if (saved && names.includes(saved)) {
    return { value: saved, banner: '' };
  }
  return {
    value: SERVER_DEFAULT_VALUE,
    banner: saved
      ? `Saved destination "${saved}" is no longer available. Using server default.`
      : '',
  };
}
