import assert from 'node:assert/strict';
import { after, afterEach, before, describe, it } from 'node:test';

globalThis.__REELDOCK_TEST__ = true;

import {
  FakeWebSocket,
  installChromeMock,
  installFetch,
  sendBackground,
  silenceIntervals,
  v2Status,
} from './helpers.mjs';

const YT = 'https://www.youtube.com/watch?v=rdSmoke01001';

const defaultStore = {
  serverUrl: 'http://127.0.0.1:8080',
  apiToken: 'tok',
  defaultDestinationFolder: 'Podcasts',
  defaultQuality: 'standard',
  embedMetadata: true,
  embedThumbnail: true,
  embedChapters: true,
  allowReimport: false,
  sponsorblockRemove: false,
  triggerAbsScan: false,
  openReelDockAfterQueue: true,
  recentJobs: [],
};

describe('background service worker', () => {
  let mocks;
  let startBackground;
  let restoreIntervals;

  before(async () => {
    restoreIntervals = silenceIntervals();
    FakeWebSocket.instances = [];
    globalThis.WebSocket = FakeWebSocket;
    mocks = installChromeMock({ store: { ...defaultStore } });
    installFetch({
      'GET /api/extension/status': v2Status(),
      'GET /api/extension/destinations': { folders: ['Podcasts', 'Sermons'], default: 'Podcasts' },
      'POST /api/extension/queue': {
        job_id: 'job-1',
        title: 'Sermon One',
        uploader: 'Church',
        status: 'queued',
        job_url: '/jobs/job-1',
      },
      'POST /api/extension/jobs/job-1/cancel': { ok: true },
      'POST /api/extension/jobs/job-1/retry': { rq_job_id: 'rq-9' },
      'GET /api/extension/jobs/job-1': {
        id: 'job-1',
        title: 'Sermon One',
        status: 'downloading',
        phase: 'downloading',
        progress_percent: 40,
        progress_label: 'Downloading',
        job_url: '/jobs/job-1',
      },
    });
    ({ startBackground } = await import('../src/background.js'));
    await startBackground();
  });

  after(() => {
    restoreIntervals?.();
  });

  afterEach(() => {
    mocks.chrome.runtime.lastError = undefined;
  });

  it('boots and answers getPublicState', async () => {
    const state = await sendBackground(mocks.onMessage, { action: 'getPublicState' });
    assert.equal(state.ok, true);
    assert.equal(state.configured, true);
    assert.equal(state.capabilities.ready, true);
    assert.equal(state.destinations.selected, 'Podcasts');
    assert.ok(!('apiToken' in state.settings));
  });

  it('rejects unknown messages', async () => {
    const unknown = await sendBackground(mocks.onMessage, { action: 'nope' });
    assert.equal(unknown.ok, false);
    const missing = await sendBackground(mocks.onMessage, {});
    assert.equal(missing.ok, false);
  });

  it('queues a youtube url and opens the job page', async () => {
    const queued = await sendBackground(mocks.onMessage, {
      action: 'queue',
      url: YT,
      source: 'popup',
    });
    assert.equal(queued.ok, true);
    assert.equal(queued.job_id, 'job-1');
    assert.ok(mocks.createdTabs.some((tab) => String(tab.url).includes('/jobs/job-1')));
    assert.ok(FakeWebSocket.instances.some((ws) => String(ws.url).includes('/api/ws/jobs/job-1')));
  });

  it('cancels and retries a job', async () => {
    await sendBackground(mocks.onMessage, { action: 'queue', url: YT, source: 'popup' });
    const cancelled = await sendBackground(mocks.onMessage, { action: 'cancel', jobId: 'job-1' });
    assert.equal(cancelled.status, 'cancelled');
    const retried = await sendBackground(mocks.onMessage, { action: 'retry', jobId: 'job-1' });
    assert.equal(retried.ok, true);
    assert.equal(retried.rq_job_id, 'rq-9');
  });

  it('opens a job and the dashboard', async () => {
    await sendBackground(mocks.onMessage, { action: 'queue', url: YT, source: 'popup' });
    const job = await sendBackground(mocks.onMessage, { action: 'openJob', jobId: 'job-1' });
    assert.equal(job.ok, true);
    const dash = await sendBackground(mocks.onMessage, { action: 'openReelDock' });
    assert.equal(dash.ok, true);
    assert.ok(mocks.createdTabs.some((tab) => tab.url === 'http://127.0.0.1:8080'));
  });

  it('loads destinations and tests a connection', async () => {
    const dest = await sendBackground(mocks.onMessage, { action: 'loadDestinations' });
    assert.equal(dest.ok, true);
    const tested = await sendBackground(mocks.onMessage, {
      action: 'testConnection',
      serverUrl: 'http://127.0.0.1:8080',
      apiToken: 'tok',
    });
    assert.equal(tested.ok, true);
    assert.equal(tested.status.api_version, 1);
    const saved = await sendBackground(mocks.onMessage, { action: 'testConnection' });
    assert.equal(saved.ok, true);
  });

  it('lists notification ids and handles notification clicks', async () => {
    const listed = await sendBackground(mocks.onMessage, { action: 'getNotificationIds' });
    assert.equal(listed.ok, true);
    assert.ok(Array.isArray(listed.ids));
    await sendBackground(mocks.onMessage, { action: 'queue', url: YT, source: 'popup' });
    mocks.onClickedNotifications.emit('reeldock-done-job-1');
    mocks.onClickedNotifications.emit('not-a-job');
  });

  it('queues from the context menu and ignores other menus', async () => {
    mocks.onClickedMenus.emit(
      { menuItemId: 'other', pageUrl: YT },
      { url: YT },
    );
    mocks.onClickedMenus.emit(
      { menuItemId: 'reeldock-queue-video', linkUrl: YT },
      { url: YT },
    );
    mocks.onClickedMenus.emit(
      { menuItemId: 'reeldock-queue-video', pageUrl: 'https://example.com' },
      { url: 'https://example.com' },
    );
  });

  it('applies storage changes and rebuilds on install', async () => {
    mocks.onChanged.emit({ apiToken: { newValue: 'tok-2' } }, 'sync');
    mocks.onChanged.emit(
      {
        apiToken: { newValue: 'tok-3' },
        serverUrl: { newValue: 'http://127.0.0.1:8080' },
      },
      'local',
    );
    mocks.onInstalled.emit();
    mocks.onStartup.emit();
  });

  it('parses websocket job updates and pings', async () => {
    await sendBackground(mocks.onMessage, { action: 'queue', url: YT, source: 'popup' });
    const ws = FakeWebSocket.instances.at(-1);
    assert.ok(ws);
    ws.onopen?.();
    ws.send = () => {};
    await ws.onmessage?.({ data: JSON.stringify({ type: 'pong' }) });
    await ws.onmessage?.({ data: JSON.stringify({ type: 'ignored' }) });
    await ws.onmessage?.({ data: 'not-json' });
    await ws.onmessage?.({
      data: JSON.stringify({
        type: 'job_update',
        job: {
          id: 'job-1',
          status: 'succeeded',
          phase: 'succeeded',
          progress_percent: 100,
          progress_label: 'Complete',
          title: 'Sermon One',
        },
      }),
    });
    ws.onerror?.(new Error('socket'));
    ws.onclose?.({ code: 1000 });
  });

  it('returns getSettings as public state', async () => {
    const settings = await sendBackground(mocks.onMessage, { action: 'getSettings' });
    assert.equal(settings.ok, true);
  });
});
