import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import {
  LEGACY_UPDATE_MESSAGE,
  parseCapabilities,
  shouldHideV2Controls,
} from '../src/capabilities.js';

describe('capabilities', () => {
  it('treats missing api_version/supports as legacy', () => {
    const legacy = parseCapabilities({ ok: true, app: 'reeldock' });
    assert.equal(legacy.ready, false);
    assert.equal(legacy.legacyMessage, LEGACY_UPDATE_MESSAGE);
    assert.equal(shouldHideV2Controls(legacy), true);
    assert.equal(legacy.supports.cancel, false);
  });

  it('enables 2.0 controls when the control plane is present', () => {
    const caps = parseCapabilities({
      api_version: 1,
      supports: { destinations: true, quality_presets: true, sponsorblock: true, cancel: true, retry: true },
    });
    assert.equal(caps.ready, true);
    assert.equal(caps.apiVersion, 1);
    assert.equal(shouldHideV2Controls(caps), false);
    assert.equal(caps.supports.destinations, true);
    assert.equal(caps.legacyMessage, '');
  });
});
