import { connectionBadge, deriveConnectionState } from './connection-state.js';
import { isYouTubeWatchUrl } from './settings.js';
import { phaseLabel, statusLabel } from './phase-labels.js';
import { isTerminalStatus } from './recent-jobs.js';

function $(id) {
  return document.getElementById(id);
}

function setStatus(text, className = 'pending') {
  const el = $('status');
  if (!el) return;
  el.textContent = text;
  el.className = className;
}

function showBanner(id, text) {
  const el = $(id);
  if (!el) return;
  if (!text) {
    el.textContent = '';
    el.classList.remove('visible');
    return;
  }
  el.textContent = text;
  el.classList.add('visible');
}

function setExtensionVersionLabel() {
  const versionEl = $('extension-version');
  if (!versionEl) return;
  versionEl.textContent = chrome.runtime?.getManifest?.().version || 'unknown';
}

let publicState = {
  settings: {},
  jobs: [],
  capabilities: { ready: false, supports: {} },
  destinations: { choices: [], selected: '', banner: '' },
  configured: false,
  connectionState: null,
};

let selectedQuality = 'standard';
let activeTab = { url: '', title: '' };
let pollTimer = null;

function hasActiveJobs(jobs = publicState.jobs) {
  return (jobs || []).some((job) => !isTerminalStatus(job.status));
}

function stopPopupPoll() {
  if (!pollTimer) return;
  clearInterval(pollTimer);
  pollTimer = null;
}

function startPopupPoll() {
  if (pollTimer) return;
  pollTimer = setInterval(async () => {
    if (!hasActiveJobs()) {
      stopPopupPoll();
      return;
    }
    try {
      await refreshState();
      renderRecent();
      if (!hasActiveJobs()) stopPopupPoll();
    } catch {
      // Keep the last rendered ledger if the worker is asleep or the server is down.
    }
  }, 2000);
}

async function getActiveTabInfo() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return { url: tab?.url || '', title: tab?.title || '' };
}

function renderCurrentVideo() {
  const videoElement = $('video');
  if (!videoElement) return;
  videoElement.replaceChildren();
  if (!isYouTubeWatchUrl(activeTab.url)) {
    videoElement.append('Not a YouTube video page.');
    return;
  }
  const title = (activeTab.title || '').trim() || activeTab.url;
  videoElement.append('Current video:');
  videoElement.appendChild(document.createElement('br'));
  const strong = document.createElement('strong');
  strong.textContent = title;
  videoElement.appendChild(strong);
}

function fillDestinationSelect() {
  const select = $('destination');
  const field = $('destination-field');
  if (!select || !field) return;
  const supports = publicState.capabilities?.supports?.destinations;
  field.classList.toggle('hidden', !supports);
  if (!supports) return;
  select.replaceChildren();
  for (const choice of publicState.destinations?.choices || [{ value: '', label: 'Server default' }]) {
    const option = document.createElement('option');
    option.value = choice.value;
    option.textContent = choice.label;
    select.appendChild(option);
  }
  select.value = publicState.destinations?.selected || '';
}

function applyQualityPills() {
  const field = $('quality-field');
  const supports = publicState.capabilities?.supports?.quality_presets;
  field?.classList.toggle('hidden', !supports);
  selectedQuality = publicState.settings.defaultQuality || 'standard';
  for (const button of document.querySelectorAll('[data-quality]')) {
    button.classList.toggle('active', button.dataset.quality === selectedQuality);
  }
}

function applyFormDefaults() {
  if ($('embed-metadata')) $('embed-metadata').checked = publicState.settings.embedMetadata !== false;
  if ($('embed-thumbnail')) $('embed-thumbnail').checked = publicState.settings.embedThumbnail !== false;
  if ($('embed-chapters')) $('embed-chapters').checked = publicState.settings.embedChapters !== false;
  if ($('sponsorblock')) $('sponsorblock').checked = Boolean(publicState.settings.sponsorblockRemove);
  if ($('allow-reimport')) $('allow-reimport').checked = Boolean(publicState.settings.allowReimport);
  $('sponsorblock-row')?.classList.toggle(
    'hidden',
    !publicState.capabilities?.supports?.sponsorblock,
  );
}

function connectionForUi() {
  return (
    publicState.connectionState ||
    deriveConnectionState({
      settings: publicState.settings,
      status: publicState.status,
      capabilities: publicState.capabilities,
      connectionError: publicState.connectionError,
      httpStatus: publicState.httpStatus,
    })
  );
}

function renderRecent() {
  const list = $('recent-list');
  if (!list) return;
  list.replaceChildren();
  const jobs = publicState.jobs || [];
  if (!jobs.length) {
    const empty = document.createElement('p');
    empty.className = 'job-meta';
    empty.textContent = 'No recent imports yet.';
    list.appendChild(empty);
    return;
  }
  for (const job of jobs) {
    const card = document.createElement('div');
    card.className = 'job';
    const title = document.createElement('div');
    title.className = 'job-title';
    title.textContent = job.title || job.jobId || 'Import';
    card.appendChild(title);
    const meta = document.createElement('div');
    meta.className = 'job-meta';
    const bits = [statusLabel(job.status)];
    if (job.uploader) bits.push(job.uploader);
    if (job.progressLabel || job.phase) bits.push(job.progressLabel || phaseLabel(job.phase, job.status));
    meta.textContent = bits.join(' · ');
    card.appendChild(meta);
    if (!isTerminalStatus(job.status)) {
      const bar = document.createElement('div');
      bar.className = 'progress-bar';
      const fill = document.createElement('div');
      fill.className = 'progress-fill';
      if (job.progressPercent == null) {
        bar.classList.add('indeterminate');
      } else {
        fill.style.width = `${Math.max(0, Math.min(100, job.progressPercent))}%`;
      }
      bar.appendChild(fill);
      card.appendChild(bar);
    }
    const actions = document.createElement('div');
    actions.className = 'job-actions';
    const supports = publicState.capabilities?.supports || {};
    const view = document.createElement('button');
    view.type = 'button';
    view.className = 'ghost';
    view.textContent = 'View';
    view.addEventListener('click', () => send({ action: 'openJob', jobId: job.jobId }));
    actions.appendChild(view);
    if (supports.cancel && !isTerminalStatus(job.status)) {
      const cancel = document.createElement('button');
      cancel.type = 'button';
      cancel.className = 'ghost';
      cancel.textContent = 'Cancel';
      cancel.addEventListener('click', () => onCancel(job.jobId));
      actions.appendChild(cancel);
    }
    if (supports.retry && (job.status === 'failed' || job.status === 'cancelled')) {
      const retry = document.createElement('button');
      retry.type = 'button';
      retry.className = 'ghost';
      retry.textContent = 'Retry';
      retry.addEventListener('click', () => onRetry(job.jobId));
      actions.appendChild(retry);
    }
    card.appendChild(actions);
    list.appendChild(card);
  }
}

async function send(message) {
  return chrome.runtime.sendMessage(message);
}

async function refreshState() {
  const res = await send({ action: 'getPublicState' });
  if (!res?.ok) throw new Error(res?.error || 'Failed to load extension state');
  publicState = res;
  return res;
}

function renderState() {
  const connection = connectionForUi();
  const badge = connectionBadge(connection.state);
  const setupPanel = $('setup-panel');
  const queueForm = $('queue-form');
  const needsSetup = ['unconfigured', 'revoked', 'authentication_error', 'server_changed'].includes(
    connection.state,
  );

  showBanner(
    'connection-banner',
    connection.state === 'connected'
      ? ''
      : `${badge.label}${connection.message ? ` — ${connection.message}` : ''}`,
  );
  showBanner('legacy-banner', publicState.legacyMessage || '');
  showBanner('dest-banner', publicState.destinations?.banner || '');

  setupPanel?.classList.toggle('hidden', !needsSetup);
  queueForm?.classList.toggle('hidden', needsSetup);
  if ($('setup-copy')) {
    $('setup-copy').textContent =
      connection.state === 'revoked' || connection.state === 'authentication_error'
        ? 'Pair this browser again from ReelDock Settings.'
        : connection.state === 'server_changed'
          ? 'This address now points to a different ReelDock server.'
          : 'Connect ReelDock before creating audiobooks.';
  }

  fillDestinationSelect();
  applyQualityPills();
  applyFormDefaults();
  renderRecent();

  const queueButton = $('queue');
  const canQueue = connection.state === 'connected' && isYouTubeWatchUrl(activeTab.url);
  if (queueButton) queueButton.disabled = !canQueue;

  if (needsSetup) {
    setStatus(connection.message || 'Connect ReelDock', 'err');
  } else if (connection.state === 'unreachable') {
    setStatus(connection.message || 'ReelDock is unavailable', 'err');
  } else if (connection.state === 'server_too_old') {
    setStatus(connection.message || 'Update ReelDock', 'err');
  } else if (!isYouTubeWatchUrl(activeTab.url)) {
    setStatus('Open a YouTube video page', 'err');
  } else {
    setStatus('Ready to create an audiobook', 'ok');
  }
}

async function onQueue(event) {
  event.preventDefault();
  if (!isYouTubeWatchUrl(activeTab.url)) {
    setStatus('Not a YouTube video URL', 'err');
    return;
  }
  const queueButton = $('queue');
  queueButton.disabled = true;
  queueButton.textContent = 'Creating…';
  try {
    setStatus('Queuing video…', 'pending');
    const res = await send({
      action: 'queue',
      source: 'popup',
      url: activeTab.url,
      destinationFolder: $('destination')?.value,
      quality: selectedQuality,
      embedMetadata: $('embed-metadata').checked,
      embedThumbnail: $('embed-thumbnail').checked,
      embedChapters: $('embed-chapters').checked,
      sponsorblockRemove: $('sponsorblock').checked,
      allowReimport: $('allow-reimport').checked,
    });
    if (!res?.ok) throw new Error(res?.error || 'Queue failed');
    setStatus(`Queued: ${res.title || res.job_id}`, 'ok');
    await refreshState();
    renderState();
    startPopupPoll();
  } catch (err) {
    setStatus(err.message || 'Queue failed', 'err');
  } finally {
    queueButton.disabled = false;
    queueButton.textContent = 'Create Audiobook';
  }
}

async function onCancel(jobId) {
  try {
    const res = await send({ action: 'cancel', jobId });
    if (!res?.ok) throw new Error(res?.error || 'Cancel failed');
    await refreshState();
    renderState();
  } catch (err) {
    setStatus(err.message || 'Cancel failed', 'err');
  }
}

async function onRetry(jobId) {
  try {
    const res = await send({ action: 'retry', jobId });
    if (!res?.ok) throw new Error(res?.error || 'Retry failed');
    await refreshState();
    renderState();
    startPopupPoll();
  } catch (err) {
    setStatus(err.message || 'Retry failed', 'err');
  }
}

$('queue-form')?.addEventListener('submit', onQueue);
$('open-reeldock')?.addEventListener('click', () => send({ action: 'openReelDock' }));
$('open-options')?.addEventListener('click', () => {
  chrome.runtime.openOptionsPage();
});

for (const button of document.querySelectorAll('[data-quality]')) {
  button.addEventListener('click', () => {
    selectedQuality = button.dataset.quality;
    for (const other of document.querySelectorAll('[data-quality]')) {
      other.classList.toggle('active', other === button);
    }
  });
}

chrome.runtime.onMessage.addListener((message) => {
  if (!message || typeof message.action !== 'string') return;
  if (message.action === 'jobUpdate' || message.action === 'jobsChanged') {
    if (Array.isArray(message.jobs)) publicState.jobs = message.jobs;
    renderRecent();
    if (hasActiveJobs()) startPopupPoll();
    else stopPopupPoll();
  }
});

setExtensionVersionLabel();

(async () => {
  try {
    activeTab = await getActiveTabInfo();
  } catch {
    activeTab = { url: '', title: '' };
  }
  renderCurrentVideo();
  try {
    await refreshState();
    renderState();
    if (hasActiveJobs()) startPopupPoll();
  } catch (err) {
    setStatus(err.message || 'Failed to load extension state', 'err');
    $('setup-panel')?.classList.remove('hidden');
  }
})();
