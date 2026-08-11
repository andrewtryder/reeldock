/** Actionable copy for extension API failures. */

export function detailText(detail) {
  if (!detail) return '';
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail.map((item) => item?.msg || String(item)).filter(Boolean).join(' ');
  }
  if (typeof detail === 'object' && detail.message) return String(detail.message);
  return '';
}

export function formatApiError(status, detail) {
  const extra = detailText(detail);
  if (status === 401) {
    return 'Not authorized. Open Options and pair this browser, or paste a legacy EXTENSION_API_TOKEN.';
  }
  if (status === 404) {
    return 'Extension API is not enabled on this ReelDock server.';
  }
  if (status === 409) {
    return extra || 'This video was already imported. Enable allow reimport to queue it again.';
  }
  if (status === 422) {
    return extra || 'ReelDock could not read this video.';
  }
  if (status >= 500) {
    return extra || 'ReelDock server error. Try again in a moment.';
  }
  return extra || `Request failed (HTTP ${status}).`;
}

export function formatCaughtError(error) {
  if (!error) return 'Unknown error';
  if (error instanceof Error) return error.message || String(error);
  return String(error);
}
