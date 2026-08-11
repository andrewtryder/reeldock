import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

globalThis.__REELDOCK_TEST__ = true;

import { installChromeMock, installFakeDom, makeElement } from './helpers.mjs';

describe('phase labels and errors', () => {
  it('maps known and unknown statuses', async () => {
    const { statusLabel, phaseLabel } = await import('../src/phase-labels.js');
    assert.equal(statusLabel('queued'), 'Queued');
    assert.equal(statusLabel('mystery'), 'mystery');
    assert.equal(statusLabel(''), 'Unknown');
    assert.equal(phaseLabel('resolving_output'), 'Preparing');
    assert.equal(phaseLabel('', 'failed'), 'Failed');
    assert.equal(phaseLabel('', ''), 'Working');
  });

  it('formats api and caught errors', async () => {
    const { detailText, formatApiError, formatCaughtError } = await import('../src/errors.js');
    assert.equal(detailText(''), '');
    assert.equal(detailText('plain'), 'plain');
    assert.equal(detailText([{ msg: 'a' }, { msg: 'b' }]), 'a b');
    assert.equal(detailText({ message: 'obj' }), 'obj');
    assert.equal(detailText(12), '');
    assert.match(formatApiError(401), /token/i);
    assert.match(formatApiError(404), /not enabled/i);
    assert.match(formatApiError(409, 'dup'), /dup|already/i);
    assert.match(formatApiError(409), /already/i);
    assert.match(formatApiError(422, 'bad'), /bad/);
    assert.match(formatApiError(422), /could not read/i);
    assert.match(formatApiError(503, 'down'), /down/);
    assert.match(formatApiError(500), /server error/i);
    assert.match(formatApiError(418), /418/);
    assert.equal(formatCaughtError(null), 'Unknown error');
    assert.equal(formatCaughtError(new Error('x')), 'x');
    assert.equal(formatCaughtError('plain'), 'plain');
  });
});

describe('ui helpers', () => {
  it('formats sizes, colors, ids, and truncation', async () => {
    const {
      truncateText,
      formatFileSize,
      getProgressColor,
      generateId,
      formatError,
      debounce,
      setStatusMessage,
      renderProgress,
    } = await import('../src/ui.js');
    assert.equal(truncateText('short'), 'short');
    assert.equal(truncateText('abcdefghijklmnopqrstuvwxyz', 10), 'abcdefg...');
    assert.equal(formatFileSize(0), '0 Bytes');
    assert.match(formatFileSize(1536, 1), /KB/);
    assert.equal(getProgressColor(10), '#4caf50');
    assert.equal(getProgressColor(50), '#ff9800');
    assert.equal(getProgressColor(90), '#f44336');
    assert.equal(generateId(6).length, 6);
    assert.equal(formatError(null), 'Unknown error');
    assert.equal(formatError(new Error('boom')), 'boom');
    assert.equal(formatError('plain'), 'plain');
    assert.match(formatError({ a: 1 }), /a/);

    const { byId } = installFakeDom(['status', 'progress-bar-fill', 'progress-label', 'progress-percentage']);
    setStatusMessage('hi', 'ok');
    assert.equal(byId.get('status').textContent, 'hi');
    renderProgress(50, 'Halfway', '50%');
    assert.equal(byId.get('progress-bar-fill').style.width, '50%');
    renderProgress();
    assert.equal(byId.get('progress-label').textContent, 'Processing...');

    let calls = 0;
    const debounced = debounce(() => {
      calls += 1;
    }, 5);
    debounced();
    debounced();
    await new Promise((resolve) => setTimeout(resolve, 20));
    assert.equal(calls, 1);
  });
});

describe('settings storage and permissions', () => {
  it('loads, saves, and requests host permission', async () => {
    const { store } = installChromeMock({
      store: {
        serverUrl: 'http://127.0.0.1:8080/',
        apiToken: 'tok',
      },
    });
    const settings = await import('../src/settings.js');
    const loaded = await settings.loadSettings();
    assert.equal(loaded.serverUrl, 'http://127.0.0.1:8080');
    assert.equal(store.serverUrl, 'http://127.0.0.1:8080');

    const saved = await settings.saveSettings({
      serverUrl: 'http://localhost:8080',
      apiToken: 'tok-2',
      defaultQuality: 'high',
    });
    assert.equal(saved.serverUrl, 'http://localhost:8080');
    assert.equal(store.apiToken, 'tok-2');

    assert.deepEqual(settings.publicSettings({ apiToken: 'secret', serverUrl: 'http://localhost:8080' }), {
      serverUrl: 'http://localhost:8080',
    });
    assert.equal(settings.optionalHostPermissionPattern('https://reeldock.example'), 'https://reeldock.example/*');
    assert.equal(await settings.ensureServerHostPermission('http://127.0.0.1:8080'), true);

    chrome.permissions.contains = async () => false;
    chrome.permissions.request = async () => true;
    assert.equal(await settings.ensureServerHostPermission('https://reeldock.example'), true);

    await settings.saveRecentJobs([{ jobId: 'a' }, { jobId: 'b' }]);
    const recent = await settings.loadRecentJobs();
    assert.equal(recent[0].jobId, 'a');
    assert.deepEqual(await settings.loadRecentJobs(), recent);
    await settings.saveRecentJobs(null);
  });
});

describe('browser api shim', () => {
  it('exports chrome when browser is undefined', async () => {
    installChromeMock();
    const api = (await import('../src/browser-api.js')).default;
    assert.equal(api.runtime.id, 'testid');
  });
});

describe('dom helper smoke', () => {
  it('creates option elements', () => {
    const select = makeElement('select', 'destination');
    const option = makeElement('option');
    option.value = 'Podcasts';
    select.appendChild(option);
    assert.equal(select.options.length, 1);
  });
});
