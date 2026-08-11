/** Destination dropdown helpers. Library root is always the empty string. */

export const LIBRARY_ROOT_VALUE = '';
export const LIBRARY_ROOT_LABEL = 'Library root';

export function destinationChoices(folders = []) {
  const names = (folders || []).filter((name) => typeof name === 'string' && name);
  return [{ value: LIBRARY_ROOT_VALUE, label: LIBRARY_ROOT_LABEL }, ...names.map((name) => ({ value: name, label: name }))];
}

/**
 * Resolve the selected destination when the saved default is stale.
 * Order: saved (if still present) → server default → library root + banner.
 */
export function resolveSavedDestination(saved, folders = [], serverDefault = '') {
  const names = folders || [];
  if (saved === LIBRARY_ROOT_VALUE || saved == null) {
    return { value: LIBRARY_ROOT_VALUE, banner: '' };
  }
  if (saved && names.includes(saved)) {
    return { value: saved, banner: '' };
  }
  if (serverDefault && names.includes(serverDefault)) {
    return {
      value: serverDefault,
      banner: saved
        ? `Saved destination "${saved}" is no longer available. Using ${serverDefault}.`
        : '',
    };
  }
  return {
    value: LIBRARY_ROOT_VALUE,
    banner: saved
      ? `Saved destination "${saved}" is no longer available. Using Library root.`
      : '',
  };
}
