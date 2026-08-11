/** Feature detection for extension control-plane 2.0. */

export const LEGACY_UPDATE_MESSAGE = 'Update ReelDock to enable all extension features.';

const DEFAULT_SUPPORTS = Object.freeze({
  destinations: false,
  quality_presets: false,
  sponsorblock: false,
  cancel: false,
  retry: false,
});

export function parseCapabilities(status) {
  const version = status?.api_version;
  const supports = status?.supports;
  if (typeof version !== 'number' || !supports || typeof supports !== 'object') {
    return {
      ready: false,
      apiVersion: 0,
      supports: { ...DEFAULT_SUPPORTS },
      legacyMessage: LEGACY_UPDATE_MESSAGE,
    };
  }
  return {
    ready: true,
    apiVersion: version,
    supports: {
      destinations: Boolean(supports.destinations),
      quality_presets: Boolean(supports.quality_presets),
      sponsorblock: Boolean(supports.sponsorblock),
      cancel: Boolean(supports.cancel),
      retry: Boolean(supports.retry),
    },
    legacyMessage: '',
  };
}

export function shouldHideV2Controls(capabilities) {
  return !capabilities?.ready;
}
