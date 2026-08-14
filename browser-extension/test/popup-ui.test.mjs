import assert from 'node:assert/strict';
import { after, before, describe, it } from 'node:test';

globalThis.__REELDOCK_TEST__ = true;

import {
  emitAsync,
  installChromeMock,
  installFakeDom,
  qualityPills,
  silenceIntervals,
} from './helpers.mjs';

const YT = 'https://www.youtube.com/watch?v=rdSmoke01001';

const POPUP_IDS = [
  'legacy-banner',
  'dest-banner',
  'video',
  'destination-field',
  'destination',
  'quality-field',
  'embed-metadata',
  'embed-thumbnail',
  'embed-chapters',
  'sponsorblock-row',
  'sponsorblock',
  'allow-reimport',
  'queue',
  'queue-form',
  'status',
  'recent',
  'recent-list',
  'open-reeldock',
  'extension-version',
];

function publicState(overrides = {}) {
  return {
    ok: true,
    settings: {
      serverUrl: 'http://127.0.0.1:8080',
      defaultQuality: 'high',
      embedMetadata: true,
      embedThumbnail: true,
      embedChapters: false,
      allowReimport: true,
      sponsorblockRemove: true,
    },
    jobs: [
      {
        jobId: 'active-1',
        title: 'Live import',
        uploader: 'Church',
        status: 'downloading',
        phase: 'downloading',
        progressPercent: 40,
        progressLabel: 'Downloading',
      },
      {
        jobId: 'indet-1',
        title: 'Indeterminate',
        status: 'running',
        phase: 'resolving_output',
        progressPercent: null,
        progressLabel: '',
      },
      {
        jobId: 'fail-1',
        title: 'Broken',
        status: 'failed',
        phase: 'failed',
        progressPercent: 0,
        errorMessage: 'boom',
      },
    ],
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
        { value: 'Podcasts', label: 'Podcasts' },
      ],
      selected: 'Podcasts',
      banner: 'Using Podcasts',
    },
    configured: true,
    legacyMessage: '',
    connectionError: '',
    connectionState: { state: 'connected', message: '', hasCredential: true },
    ...overrides,
  };
}

describe('popup ui', () => {
  let chromeMock;
  let byId;
  let startPopup;
  let lastQueue;
  let restoreIntervals;

  before(async () => {
    restoreIntervals = silenceIntervals();
    const pills = qualityPills();
    ({ byId } = installFakeDom(POPUP_IDS, pills));
    chromeMock = installChromeMock({
      tabs: [{ url: YT, title: 'Sermon One' }],
    });
    chromeMock.chrome.runtime.sendMessage = async (message) => {
      if (message.action === 'getPublicState') return publicState();
      if (message.action === 'queue') {
        lastQueue = message;
        return { ok: true, job_id: 'job-9', title: 'Sermon One' };
      }
      if (message.action === 'cancel') return { ok: true };
      if (message.action === 'retry') return { ok: true };
      if (message.action === 'openJob' || message.action === 'openReelDock') return { ok: true };
      return { ok: false, error: `unexpected ${message.action}` };
    };
    ({ startPopup } = await import('../src/popup.js'));
    await startPopup();
  });

  after(() => {
    restoreIntervals?.();
  });

  it('renders the current video and version', () => {
    assert.equal(byId.get('extension-version').textContent, '1.11.0');
    assert.match(byId.get('video')._children.at(-1).textContent, /Sermon One/);
    assert.equal(byId.get('queue').disabled, false);
    assert.equal(byId.get('status').textContent, 'Ready to create an audiobook');
  });

  it('queues from the form and toggles quality', async () => {
    const high = document.querySelectorAll('[data-quality]').find((el) => el.dataset.quality === 'high');
    high.click();
    byId.get('destination').value = 'Podcasts';
    byId.get('embed-metadata').checked = true;
    byId.get('allow-reimport').checked = true;
    await emitAsync(byId.get('queue-form'), 'submit');
    assert.equal(lastQueue.action, 'queue');
    assert.equal(lastQueue.url, YT);
    assert.equal(lastQueue.quality, 'high');
    assert.equal(lastQueue.destinationFolder, 'Podcasts');
  });

  it('opens reeldock and handles job updates', async () => {
    byId.get('open-reeldock').click();
    const listener = chromeMock.chrome.runtime.onMessage.listeners[0];
    listener({ action: 'ignored' });
    listener(null);
    listener({
      action: 'jobsChanged',
      jobs: [
        {
          jobId: 'done-1',
          title: 'Done',
          status: 'succeeded',
          phase: 'succeeded',
        },
      ],
    });
    assert.match(byId.get('recent-list')._children[0].textContent || byId.get('recent-list')._children[0]._children?.[0]?.textContent || '', /Done|Complete|succeeded/i);
  });

  it('wires cancel and retry on recent cards', async () => {
    const listener = chromeMock.chrome.runtime.onMessage.listeners[0];
    listener({
      action: 'jobsChanged',
      jobs: publicState().jobs,
    });
    const buttons = [];
    const walk = (node) => {
      if (!node) return;
      if (node.textContent === 'Cancel' || node.textContent === 'Retry' || node.textContent === 'View') {
        buttons.push(node);
      }
      for (const child of node._children || []) walk(child);
    };
    walk(byId.get('recent-list'));
    for (const button of buttons) {
      await button.click();
    }
    assert.ok(buttons.length >= 2);
  });
});
