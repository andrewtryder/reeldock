import assert from 'node:assert/strict';
import { before, describe, it } from 'node:test';

globalThis.__REELDOCK_TEST__ = true;

import {
  emitAsync,
  installChromeMock,
  installFakeDom,
  qualityPills,
  v2Status,
} from './helpers.mjs';

const OPTION_IDS = [
  'serverUrl',
  'apiToken',
  'defaultDestinationFolder',
  'defaultQuality',
  'embedMetadata',
  'embedThumbnail',
  'embedChapters',
  'sponsorblockRemove',
  'triggerAbsScan',
  'allowReimport',
  'openReelDockAfterQueue',
  'destinationSelect',
  'destination-select-wrap',
  'destination-text-wrap',
  'quality-wrap',
  'sponsorblock-row',
  'abs-row',
  'legacy-banner',
  'dest-banner',
  'save',
  'test',
  'status',
  'status-panel',
  'status-indicator',
  'connection-status',
  'dry-run-status',
  'abs-configured',
  'playlists-allowed',
  'channels-allowed',
  'api-status',
  'overall-status',
  'overall-status-indicator',
];

describe('options ui', () => {
  let byId;
  let store;
  let startOptions;
  let testPayload;

  before(async () => {
    ({ byId } = installFakeDom(OPTION_IDS, qualityPills()));
    ({ store } = installChromeMock({
      store: {
        serverUrl: 'http://127.0.0.1:8080',
        apiToken: 'tok',
        defaultQuality: 'best',
        embedMetadata: true,
        embedThumbnail: true,
        embedChapters: true,
        allowReimport: false,
        sponsorblockRemove: false,
        triggerAbsScan: true,
        openReelDockAfterQueue: false,
        defaultDestinationFolder: 'Podcasts',
      },
    }));
    chrome.runtime.sendMessage = async (message) => {
      if (message.action === 'getPublicState' || message.action === 'testConnection') {
        testPayload = {
          ok: true,
          status: v2Status({ dry_run: true, allow_playlists: true, allow_channels: true }),
          capabilities: {
            ready: true,
            supports: {
              destinations: true,
              quality_presets: true,
              sponsorblock: true,
              cancel: true,
              retry: true,
            },
          },
          destinations: {
            choices: [
              { value: '', label: 'Server default' },
              { value: 'Sermons', label: 'Sermons' },
            ],
            selected: 'Sermons',
            banner: 'Using Sermons',
          },
        };
        return testPayload;
      }
      return { ok: false, error: 'unexpected' };
    };
    ({ startOptions } = await import('../src/options.js'));
    await startOptions();
  });

  it('populates saved settings and applies capabilities', () => {
    assert.equal(byId.get('serverUrl').value, 'http://127.0.0.1:8080');
    assert.equal(byId.get('apiToken').value, 'tok');
    assert.equal(byId.get('defaultQuality').value, 'best');
    assert.equal(byId.get('quality-wrap').classList.contains('hidden'), false);
    assert.equal(byId.get('destination-select-wrap').classList.contains('hidden'), false);
  });

  it('saves settings after picking a quality pill', async () => {
    const high = document.querySelectorAll('[data-quality]').find((el) => el.dataset.quality === 'high');
    assert.ok(high);
    await emitAsync(high, 'click');
    assert.equal(byId.get('defaultQuality').value, 'high');
    byId.get('openReelDockAfterQueue').checked = true;
    await emitAsync(byId.get('save'), 'click');
    assert.equal(store.defaultQuality, 'high');
    assert.equal(store.openReelDockAfterQueue, true);
    assert.match(byId.get('status').textContent, /saved|Connected|OK|successfully/i);
  });

  it('tests the connection and fills the status panel', async () => {
    chrome.runtime.sendMessage = async (message) => {
      if (message.action === 'testConnection') {
        return {
          ok: true,
          status: v2Status({
            ok: false,
            dry_run: false,
            abs_configured: false,
            allow_playlists: false,
            allow_channels: false,
            extension_api_enabled: false,
          }),
          capabilities: { ready: false, supports: {} },
          destinations: { choices: [], selected: '', banner: '' },
        };
      }
      return { ok: true, capabilities: { ready: false, supports: {} } };
    };
    await emitAsync(byId.get('test'), 'click');
    assert.ok(byId.get('status').textContent);
  });

  it('rejects an empty token on save', async () => {
    byId.get('serverUrl').value = 'http://127.0.0.1:8080';
    byId.get('apiToken').value = '';
    await emitAsync(byId.get('save'), 'click');
    assert.match(byId.get('status').textContent, /token/i);
  });

  it('rejects a bad server url', async () => {
    byId.get('serverUrl').value = 'not-a-url';
    byId.get('apiToken').value = 'tok';
    await emitAsync(byId.get('save'), 'click');
    assert.ok(byId.get('status').textContent);
  });
});
