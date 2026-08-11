import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import {
  buildQueuePayload,
  normalizeQuality,
  shouldOpenReelDockAfterQueue,
} from '../src/queue-payload.js';
import { DEFAULT_SETTINGS } from '../src/settings.js';

describe('queue payload', () => {
  it('maps presets and flags onto the API body', () => {
    const body = buildQueuePayload({
      url: 'https://www.youtube.com/watch?v=abcdefghijk',
      destinationFolder: 'Theology',
      quality: 'high',
      sponsorblockRemove: true,
      embedMetadata: true,
      triggerAbsScan: true,
      allowReimport: false,
    });
    assert.equal(body.quality, 'high');
    assert.equal(body.sponsorblock_remove, true);
    assert.equal(body.destination_folder, 'Theology');
    assert.equal(body.trigger_abs_scan, true);
    assert.equal(body.allow_reimport, false);
  });

  it('defaults quality to standard and rejects unknown names', () => {
    assert.equal(normalizeQuality('best'), 'best');
    assert.equal(normalizeQuality('ultra'), 'standard');
    assert.equal(buildQueuePayload({ url: 'https://youtu.be/abcdefghijk' }).quality, 'standard');
  });

  it('omits destination_folder for server default and sends empty string for root', () => {
    const omitted = buildQueuePayload({ url: 'https://youtu.be/abcdefghijk' });
    assert.equal('destination_folder' in omitted, false);

    const serverDefault = buildQueuePayload({
      url: 'https://youtu.be/abcdefghijk',
      destinationFolder: '',
    });
    assert.equal('destination_folder' in serverDefault, false);

    const root = buildQueuePayload({
      url: 'https://youtu.be/abcdefghijk',
      destinationFolder: '__root__',
    });
    assert.equal(root.destination_folder, '');
  });

  it('does not open ReelDock after queue unless the setting is true', () => {
    assert.equal(shouldOpenReelDockAfterQueue(DEFAULT_SETTINGS), false);
    assert.equal(shouldOpenReelDockAfterQueue({ openReelDockAfterQueue: false }), false);
    assert.equal(shouldOpenReelDockAfterQueue({ openReelDockAfterQueue: true }), true);
  });
});
