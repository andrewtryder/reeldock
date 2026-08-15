// Background service worker owns ReelDock HTTP/WS, the recent-job ledger,
// cancel/retry, notifications, and rehydration. Popup/options only message us.

import { parseCapabilities } from './capabilities.js';
import { deriveConnectionState } from './connection-state.js';
import { destinationChoices, resolveSavedDestination } from './destinations.js';
import { formatApiError, formatCaughtError } from './errors.js';
import {
  parseNotificationJobId,
  queuedNotificationSpec,
  releaseTerminalNotificationClaim,
  claimTerminalNotification,
  terminalNotificationSpec,
} from './notifications.js';
import {
  applyJobPatch,
  displayRecentJobs,
  droppedJobIds,
  isTerminalStatus,
  jobMatchesServerOrigin,
  mergeJobFromServer,
  resetJobForRetry,
  upsertRecentJob,
} from './recent-jobs.js';
import {
  buildQueuePayload,
  shouldOpenReelDockAfterQueue,
} from './queue-payload.js';
import { applyDeviceRevoke, isDeviceToken } from './pairing.js';
import {
  DEFAULT_SETTINGS,
  SETTINGS_KEYS,
  isYouTubeWatchUrl,
  loadRecentJobs,
  loadSettings,
  publicSettings,
  requireValidatedServerOrigin,
  saveRecentJobs,
  saveSettings,
} from './settings.js';

const CONTEXT_MENU_ID = 'reeldock-queue-video';

let settings = { ...DEFAULT_SETTINGS };
let recentJobs = [];
let capabilities = parseCapabilities(null);
let lastStatus = null;
let connectionError = '';
let lastHttpStatus = null;
let destinationState = {
  folders: [],
  default: '',
  selected: '',
  banner: '',
  choices: destinationChoices([]),
};

const activeWebSockets = new Map();
const RECONCILE_INTERVAL_MS = 2000;
let reconcileTimer = null;
let reconcileInFlight = false;

function authHeaders(token = settings.apiToken) {
  const headers = { 'Content-Type': 'application/json' };
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  return headers;
}

function configuredServerOrigin() {
  if (!settings.serverUrl) {
    throw new Error('Server URL not configured. Open the extension options to set it.');
  }
  return requireValidatedServerOrigin(settings.serverUrl);
}

function currentServerOrigin() {
  try {
    return configuredServerOrigin();
  } catch {
    return '';
  }
}

async function persistJobs(next) {
  const previous = recentJobs;
  recentJobs = next;
  for (const jobId of droppedJobIds(previous, recentJobs)) {
    stopJobWebSocket(jobId, 'Dropped from recent jobs');
  }
  await saveRecentJobs(recentJobs);
}

async function refreshSettings() {
  const previousOrigin = settings.serverUrl;
  settings = await loadSettings();
  recentJobs = await loadRecentJobs();
  if (previousOrigin && settings.serverUrl && previousOrigin !== settings.serverUrl) {
    stopSocketsForOtherOrigins();
  }
}

async function parseErrorResponse(response) {
  let detail;
  try {
    const body = await response.json();
    detail = body?.detail;
  } catch {
    try {
      detail = await response.text();
    } catch {
      detail = response.statusText;
    }
  }
  const error = new Error(formatApiError(response.status, detail));
  error.status = response.status;
  return error;
}

async function apiFetch(path, options = {}) {
  const { serverOrigin, apiToken, ...fetchOptions } = options;
  const base = serverOrigin || configuredServerOrigin();
  let response;
  try {
    response = await fetch(`${base}${path}`, {
      ...fetchOptions,
      headers: { ...authHeaders(apiToken), ...(fetchOptions.headers || {}) },
    });
  } catch (err) {
    lastHttpStatus = null;
    throw err;
  }
  if (!response.ok) {
    lastHttpStatus = response.status;
    throw await parseErrorResponse(response);
  }
  lastHttpStatus = response.status;
  if (response.status === 204) return null;
  return response.json();
}

async function rememberSuccessfulConnection(status) {
  const patch = { lastConnectedAt: Date.now() };
  if (!settings.pairedServerInstanceId && status?.instance_id) {
    patch.pairedServerInstanceId = String(status.instance_id);
  }
  if (status?.device_id) {
    patch.deviceId = String(status.device_id);
  }
  if (status?.device_name) {
    patch.deviceName = String(status.device_name);
  }
  await saveSettings(patch);
  settings = { ...settings, ...patch };
}

const CREATED_NOTIFICATION_IDS_KEY = 'createdNotificationIds';

async function rememberNotificationId(id) {
  if (!id) return;
  try {
    const stored = await chrome.storage.local.get(CREATED_NOTIFICATION_IDS_KEY);
    const current = Array.isArray(stored[CREATED_NOTIFICATION_IDS_KEY])
      ? stored[CREATED_NOTIFICATION_IDS_KEY]
      : [];
    if (current.includes(id)) return;
    await chrome.storage.local.set({
      [CREATED_NOTIFICATION_IDS_KEY]: [...current, id].slice(-20),
    });
  } catch (err) {
    console.warn('Could not persist notification id:', err);
  }
}

function notifySpec(spec) {
  if (!spec) return;
  rememberNotificationId(spec.id).catch((err) => {
    console.warn('Notification id persist failed:', err);
  });
  try {
    chrome.notifications?.create(
      spec.id,
      {
        type: 'basic',
        iconUrl: chrome.runtime.getURL('icons/icon-128.png'),
        title: spec.title,
        message: String(spec.message || ''),
      },
      () => {
        const lastError = chrome.runtime.lastError;
        if (lastError) {
          console.error('Notification failed:', lastError.message);
        }
      },
    );
  } catch (err) {
    console.error('Notification failed:', err);
  }
}

async function listedNotificationIds() {
  let live = [];
  try {
    live = Object.keys((await chrome.notifications?.getAll?.()) || {});
  } catch {
    live = [];
  }
  let stored = [];
  try {
    const data = await chrome.storage.local.get(CREATED_NOTIFICATION_IDS_KEY);
    stored = Array.isArray(data[CREATED_NOTIFICATION_IDS_KEY])
      ? data[CREATED_NOTIFICATION_IDS_KEY]
      : [];
  } catch {
    stored = [];
  }
  return [...new Set([...live, ...stored])];
}

async function maybeNotifyTerminal(jobId) {
  const job = recentJobs.find((item) => item.jobId === jobId);
  const spec = terminalNotificationSpec(job);
  if (!spec) return;
  if (!claimTerminalNotification(jobId)) return;
  await persistJobs(applyJobPatch(recentJobs, jobId, { terminalNotificationSent: true }));
  notifySpec(spec);
}

async function openAbsoluteOrJobUrl(jobUrl, serverOrigin) {
  if (!jobUrl) return;
  if (jobUrl.startsWith('http://') || jobUrl.startsWith('https://')) {
    await chrome.tabs.create({ url: jobUrl });
    return;
  }
  const base = serverOrigin || configuredServerOrigin();
  await chrome.tabs.create({ url: `${base}${jobUrl}` });
}

function broadcast(message) {
  chrome.runtime.sendMessage(message).catch(() => {
    // Popup may be closed.
  });
}

function publicState() {
  const connectionState = deriveConnectionState({
    settings,
    status: lastStatus,
    capabilities,
    connectionError,
    httpStatus: lastHttpStatus,
  });
  return {
    ok: true,
    settings: publicSettings(settings),
    jobs: displayRecentJobs(recentJobs),
    capabilities,
    destinations: destinationState,
    status: lastStatus,
    configured: Boolean(settings.serverUrl && settings.apiToken),
    legacyMessage: connectionError ? '' : capabilities.legacyMessage || '',
    connectionError,
    httpStatus: lastHttpStatus,
    connectionState,
  };
}

async function fetchStatus() {
  lastStatus = await apiFetch('/api/extension/status');
  capabilities = parseCapabilities(lastStatus);
  if (lastStatus?.ok) {
    await rememberSuccessfulConnection(lastStatus);
  }
  return lastStatus;
}

async function fetchDestinations(fetchOptions = {}) {
  if (!capabilities.supports.destinations) {
    destinationState = {
      folders: [],
      default: '',
      selected: settings.defaultDestinationFolder || '',
      banner: '',
      choices: destinationChoices([]),
    };
    return destinationState;
  }
  const data = await apiFetch('/api/extension/destinations', fetchOptions);
  const folders = Array.isArray(data.folders) ? data.folders : [];
  const serverDefault = data.default || '';
  const resolved = resolveSavedDestination(
    settings.defaultDestinationFolder || '',
    folders,
    serverDefault,
  );
  destinationState = {
    folders,
    default: serverDefault,
    selected: resolved.value,
    banner: resolved.banner,
    choices: destinationChoices(folders, serverDefault),
  };
  return destinationState;
}

async function fetchJob(jobId) {
  return apiFetch(`/api/extension/jobs/${encodeURIComponent(jobId)}`);
}

function jobsOnCurrentServer() {
  const origin = currentServerOrigin();
  return recentJobs.filter((job) => jobMatchesServerOrigin(job, origin));
}

async function reconcileActiveJobs() {
  const origin = currentServerOrigin();
  const active = recentJobs.filter(
    (job) => !isTerminalStatus(job.status) && jobMatchesServerOrigin(job, origin),
  );
  let changed = false;
  for (const job of active) {
    try {
      const fresh = await fetchJob(job.jobId);
      const merged = mergeJobFromServer(fresh, job);
      const snapshot = `${job.status}:${job.phase}:${job.progressPercent}:${job.progressLabel}`;
      const nextSnap = `${merged.status}:${merged.phase}:${merged.progressPercent}:${merged.progressLabel}`;
      await persistJobs(upsertRecentJob(recentJobs, merged));
      if (snapshot !== nextSnap) changed = true;
      if (isTerminalStatus(merged.status)) {
        stopJobWebSocket(job.jobId, 'Job finished');
        await maybeNotifyTerminal(job.jobId);
      } else {
        startJobWebSocket(job.jobId);
      }
    } catch (err) {
      // Keep the local record. Do not mark the job failed if the server is down.
      console.warn(`Reconcile skipped for ${job.jobId}:`, formatCaughtError(err));
    }
  }
  return changed;
}

function hasActiveJobs() {
  return jobsOnCurrentServer().some((job) => !isTerminalStatus(job.status));
}

function stopReconcileLoop() {
  if (!reconcileTimer) return;
  clearInterval(reconcileTimer);
  reconcileTimer = null;
}

function startReconcileLoop() {
  if (reconcileTimer) return;
  reconcileTimer = setInterval(() => {
    tickReconcile().catch((err) => console.warn('Reconcile tick failed:', err));
  }, RECONCILE_INTERVAL_MS);
}

async function tickReconcile() {
  if (reconcileInFlight) return;
  if (!hasActiveJobs()) {
    stopReconcileLoop();
    return;
  }
  reconcileInFlight = true;
  try {
    const changed = await reconcileActiveJobs();
    if (changed) {
      broadcast({ action: 'jobsChanged', jobs: displayRecentJobs(recentJobs) });
    }
    if (!hasActiveJobs()) stopReconcileLoop();
  } finally {
    reconcileInFlight = false;
  }
}

async function handleTestConnection(message = {}) {
  connectionError = '';
  lastHttpStatus = null;
  try {
    const ephemeralUrl = typeof message.serverUrl === 'string' ? message.serverUrl.trim() : '';
    const hasEphemeralToken = typeof message.apiToken === 'string';
    if (ephemeralUrl || hasEphemeralToken) {
      const origin = requireValidatedServerOrigin(ephemeralUrl || settings.serverUrl);
      const token = hasEphemeralToken ? message.apiToken : settings.apiToken;
      const fetchOptions = { serverOrigin: origin, apiToken: token };
      lastStatus = await apiFetch('/api/extension/status', fetchOptions);
      capabilities = parseCapabilities(lastStatus);
      if (lastStatus?.ok) {
        await rememberSuccessfulConnection(lastStatus);
      }
      try {
        await fetchDestinations(fetchOptions);
      } catch (err) {
        console.warn('Destinations unavailable:', formatCaughtError(err));
      }
      return {
        ...publicState(),
        ok: true,
        status: lastStatus,
        capabilities,
        destinations: destinationState,
      };
    }
    await refreshSettings();
    const status = await fetchStatus();
    try {
      await fetchDestinations();
    } catch (err) {
      console.warn('Destinations unavailable:', formatCaughtError(err));
    }
    return {
      ...publicState(),
      ok: true,
      status,
      capabilities,
      destinations: destinationState,
    };
  } catch (err) {
    connectionError = formatCaughtError(err);
    if (typeof err?.status === 'number') lastHttpStatus = err.status;
    return {
      ...publicState(),
      ok: false,
      error: connectionError,
    };
  }
}

async function clearLocalDeviceSession(reason) {
  closeAllWebSockets(reason);
  await saveSettings({
    apiToken: '',
    deviceId: '',
    deviceName: '',
    pairedServerInstanceId: '',
    lastConnectedAt: 0,
  });
  lastStatus = null;
  lastHttpStatus = null;
  connectionError = '';
  await refreshSettings();
}

async function handleRevokeDevice() {
  await refreshSettings();
  try {
    return await applyDeviceRevoke({
      isDevice: isDeviceToken(settings.apiToken),
      revokeRemote: () => apiFetch('/api/extension/devices/me/revoke', { method: 'POST' }),
      clearLocal: () => clearLocalDeviceSession('Device revoked'),
    });
  } catch (err) {
    return { ok: false, error: formatCaughtError(err) };
  }
}

async function handleLocalDisconnect() {
  await clearLocalDeviceSession('Disconnected locally');
  return { ok: true, status: 'disconnected' };
}

async function handleLoadDestinations() {
  await refreshSettings();
  try {
    await fetchStatus();
  } catch (err) {
    console.warn('Status unavailable:', formatCaughtError(err));
  }
  await fetchDestinations();
  return { ok: true, destinations: destinationState, capabilities };
}

async function handleGetPublicState() {
  await refreshSettings();
  connectionError = '';
  lastHttpStatus = null;
  if (settings.serverUrl && settings.apiToken) {
    try {
      await fetchStatus();
      await fetchDestinations();
    } catch (err) {
      connectionError = formatCaughtError(err);
      if (typeof err?.status === 'number') lastHttpStatus = err.status;
      console.warn('Public state status/destinations failed:', connectionError);
    }
    await reconcileActiveJobs();
    if (hasActiveJobs()) startReconcileLoop();
  }
  return publicState();
}

async function handleQueue(message) {
  await refreshSettings();
  const url = message.url || '';
  if (!isYouTubeWatchUrl(url)) {
    throw new Error('Not a YouTube video URL.');
  }
  const source = message.source === 'contextMenu' ? 'contextMenu' : 'popup';
  const payload = buildQueuePayload({
    url,
    destinationFolder:
      message.destinationFolder ?? settings.defaultDestinationFolder ?? destinationState.selected,
    outputTitle: message.outputTitle || '',
    embedMetadata: message.embedMetadata ?? settings.embedMetadata,
    embedThumbnail: message.embedThumbnail ?? settings.embedThumbnail,
    embedChapters: message.embedChapters ?? settings.embedChapters,
    triggerAbsScan: message.triggerAbsScan ?? settings.triggerAbsScan,
    allowReimport: message.allowReimport ?? settings.allowReimport,
    quality: message.quality ?? settings.defaultQuality,
    sponsorblockRemove: message.sponsorblockRemove ?? settings.sponsorblockRemove,
  });
  const data = await apiFetch('/api/extension/queue', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
  if (!data?.job_id) {
    throw new Error('Queue response missing job_id');
  }
  const origin = configuredServerOrigin();
  const record = {
    jobId: data.job_id,
    title: data.title || '',
    uploader: data.uploader || '',
    status: data.status || 'queued',
    phase: 'queued',
    progressPercent: null,
    progressLabel: 'Queued',
    jobUrl: data.job_url || `/jobs/${data.job_id}`,
    serverOrigin: origin,
    createdAt: new Date().toISOString(),
    errorMessage: '',
    terminalNotificationSent: false,
  };
  await persistJobs(upsertRecentJob(recentJobs, record));
  notifySpec(queuedNotificationSpec(record, { source }));
  if (shouldOpenReelDockAfterQueue(settings)) {
    await openAbsoluteOrJobUrl(record.jobUrl, origin);
  }
  startJobWebSocket(record.jobId);
  startReconcileLoop();
  broadcast({ action: 'jobsChanged', jobs: displayRecentJobs(recentJobs) });
  return {
    ok: true,
    job_id: record.jobId,
    jobId: record.jobId,
    status: record.status,
    title: record.title,
    uploader: record.uploader,
    job_url: record.jobUrl,
    jobUrl: record.jobUrl,
    serverUrl: origin,
  };
}

async function handleCancel(jobId) {
  await refreshSettings();
  await apiFetch(`/api/extension/jobs/${encodeURIComponent(jobId)}/cancel`, { method: 'POST' });
  await persistJobs(applyJobPatch(recentJobs, jobId, { status: 'cancelled', phase: 'cancelled' }));
  stopJobWebSocket(jobId, 'Cancelled');
  await maybeNotifyTerminal(jobId);
  broadcast({ action: 'jobsChanged', jobs: displayRecentJobs(recentJobs) });
  return { ok: true, jobId, status: 'cancelled' };
}

async function handleRetry(jobId) {
  await refreshSettings();
  const data = await apiFetch(`/api/extension/jobs/${encodeURIComponent(jobId)}/retry`, {
    method: 'POST',
  });
  const existing = recentJobs.find((job) => job.jobId === jobId);
  releaseTerminalNotificationClaim(jobId);
  const reset = resetJobForRetry(existing || { jobId });
  await persistJobs(upsertRecentJob(recentJobs, reset));
  startJobWebSocket(jobId);
  startReconcileLoop();
  broadcast({ action: 'jobsChanged', jobs: displayRecentJobs(recentJobs) });
  return { ok: true, jobId, status: 'queued', rq_job_id: data?.rq_job_id || null };
}

async function handleOpenJob(jobId) {
  await refreshSettings();
  const job = recentJobs.find((item) => item.jobId === jobId);
  await openAbsoluteOrJobUrl(job?.jobUrl || `/jobs/${jobId}`, job?.serverOrigin);
  return { ok: true };
}

async function handleOpenReelDock() {
  await refreshSettings();
  const base = configuredServerOrigin();
  await chrome.tabs.create({ url: base });
  return { ok: true };
}

async function buildJobWebSocketUrl(jobId) {
  const base = new URL(configuredServerOrigin());
  const wsProtocol = base.protocol === 'http:' ? 'ws:' : 'wss:';
  const wsUrl = new URL(`${wsProtocol}//${base.host}/api/ws/jobs/${encodeURIComponent(jobId)}`);
  if (isDeviceToken(settings.apiToken)) {
    const payload = await apiFetch('/api/extension/ws-ticket', {
      method: 'POST',
      body: JSON.stringify({ job_id: jobId }),
    });
    if (!payload?.ticket) {
      throw new Error('ReelDock did not issue a WebSocket ticket.');
    }
    wsUrl.searchParams.set('ticket', payload.ticket);
    return wsUrl.toString();
  }
  if (settings.apiToken) {
    wsUrl.searchParams.set('token', settings.apiToken);
  }
  return wsUrl.toString();
}

function stopJobWebSocket(jobId, reason = 'Stopped') {
  const ws = activeWebSockets.get(jobId);
  if (!ws) return;
  if (ws.keepaliveInterval) clearInterval(ws.keepaliveInterval);
  try {
    ws.close(1000, reason);
  } catch {
    // ignore
  }
  activeWebSockets.delete(jobId);
}

function closeAllWebSockets(reason) {
  for (const jobId of [...activeWebSockets.keys()]) {
    stopJobWebSocket(jobId, reason);
  }
}

function stopSocketsForOtherOrigins() {
  const origin = currentServerOrigin();
  for (const job of recentJobs) {
    if (!jobMatchesServerOrigin(job, origin)) {
      stopJobWebSocket(job.jobId, 'Server origin changed');
    }
  }
}

function startJobWebSocket(jobId) {
  void startJobWebSocketAsync(jobId);
  return activeWebSockets.get(jobId) || null;
}

async function startJobWebSocketAsync(jobId) {
  if (!settings.serverUrl) return null;
  const job = recentJobs.find((item) => item.jobId === jobId);
  if (job && !jobMatchesServerOrigin(job, currentServerOrigin())) {
    return null;
  }
  const existing = activeWebSockets.get(jobId);
  if (existing && (existing.readyState === WebSocket.OPEN || existing.readyState === WebSocket.CONNECTING)) {
    return existing;
  }

  let ws;
  try {
    const url = await buildJobWebSocketUrl(jobId);
    ws = new WebSocket(url);
  } catch (error) {
    console.error(`Cannot start WebSocket for job ${jobId}:`, error);
    return null;
  }

  ws.onopen = function onOpen() {
    ws.keepaliveInterval = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'ping' }));
      }
    }, 30000);
  };

  ws.onmessage = async function onMessage(event) {
    try {
      const data = JSON.parse(event.data);
      if (data.type === 'pong') return;
      if (data.type !== 'job_update' || !data.job) return;
      const current = recentJobs.find((job) => job.jobId === jobId) || { jobId };
      const merged = mergeJobFromServer(data.job, current);
      await persistJobs(upsertRecentJob(recentJobs, merged));
      if (isTerminalStatus(merged.status)) {
        stopJobWebSocket(jobId, 'Job finished');
        await maybeNotifyTerminal(jobId);
      }
      broadcast({ action: 'jobUpdate', job: merged, jobs: displayRecentJobs(recentJobs) });
    } catch (error) {
      console.error('Error parsing WebSocket message:', error);
    }
  };

  ws.onclose = function onClose(event) {
    if (ws.keepaliveInterval) clearInterval(ws.keepaliveInterval);
    activeWebSockets.delete(jobId);
    if (event.code !== 1000 && event.code !== 1001) {
      const job = recentJobs.find((item) => item.jobId === jobId);
      if (job && !isTerminalStatus(job.status)) {
        setTimeout(() => startJobWebSocket(jobId), 5000);
      }
    }
  };

  ws.onerror = function onError(error) {
    console.error(`WebSocket error for job ${jobId}:`, error);
  };

  activeWebSockets.set(jobId, ws);
  return ws;
}

function createContextMenus() {
  chrome.contextMenus.remove(CONTEXT_MENU_ID, () => {
    const removeError = chrome.runtime.lastError;
    if (removeError && !removeError.message?.includes('Cannot find menu item')) {
      console.error('Context menu cleanup failed:', removeError.message);
      return;
    }
    chrome.contextMenus.create(
      {
        id: CONTEXT_MENU_ID,
        title: 'Send to ReelDock',
        contexts: ['page', 'link'],
        documentUrlPatterns: [
          'https://www.youtube.com/*',
          'https://youtube.com/*',
          'https://m.youtube.com/*',
          'https://youtu.be/*',
        ],
      },
      () => {
        const createError = chrome.runtime.lastError;
        if (createError && !createError.message?.includes('duplicate id')) {
          console.error('Context menu setup failed:', createError.message);
        }
      },
    );
  });
}

function urlFromContextMenu(info, tab) {
  return info.linkUrl || info.pageUrl || tab?.url || '';
}

function replyAsync(sendResponse, promise) {
  promise.then(
    (data) => sendResponse(data),
    (err) => sendResponse({ ok: false, error: formatCaughtError(err) }),
  );
  return true;
}

export function startBackground() {
  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (!message || typeof message.action !== 'string') {
    sendResponse({ ok: false, error: 'Unknown message' });
    return false;
  }

  if (message.action === 'getPublicState' || message.action === 'getSettings') {
    return replyAsync(sendResponse, handleGetPublicState());
  }
  if (message.action === 'queue') {
    return replyAsync(sendResponse, handleQueue(message));
  }
  if (message.action === 'cancel') {
    return replyAsync(sendResponse, handleCancel(message.jobId));
  }
  if (message.action === 'retry') {
    return replyAsync(sendResponse, handleRetry(message.jobId));
  }
  if (message.action === 'openJob') {
    return replyAsync(sendResponse, handleOpenJob(message.jobId));
  }
  if (message.action === 'openReelDock') {
    return replyAsync(sendResponse, handleOpenReelDock());
  }
  if (message.action === 'loadDestinations') {
    return replyAsync(sendResponse, handleLoadDestinations());
  }
  if (message.action === 'testConnection') {
    return replyAsync(sendResponse, handleTestConnection(message));
  }
  if (message.action === 'revokeDevice') {
    return replyAsync(sendResponse, handleRevokeDevice());
  }
  if (message.action === 'disconnectLocal') {
    return replyAsync(sendResponse, handleLocalDisconnect());
  }
  if (message.action === 'getNotificationIds') {
    return replyAsync(sendResponse, listedNotificationIds().then((ids) => ({ ok: true, ids })));
  }

  sendResponse({ ok: false, error: `Unknown action: ${message.action}` });
  return false;
});

chrome.contextMenus.onClicked.addListener((info, tab) => {
  if (info.menuItemId !== CONTEXT_MENU_ID) return;
  handleQueue({ url: urlFromContextMenu(info, tab), source: 'contextMenu' }).catch((err) => {
    console.error('Context menu queue failed:', err);
    notifySpec({
      id: `reeldock-fail-context-${Date.now()}`,
      title: 'ReelDock',
      message: formatCaughtError(err),
    });
  });
});

chrome.notifications?.onClicked?.addListener((notificationId) => {
  const jobId = parseNotificationJobId(notificationId);
  if (!jobId) return;
  handleOpenJob(jobId).catch((err) => {
    console.error('Notification click failed:', err);
  });
});

chrome.storage.onChanged.addListener((changes, area) => {
  if (area !== 'local') return;
  for (const key of SETTINGS_KEYS) {
    if (key in changes) settings[key] = changes[key].newValue;
  }
  if (changes.serverUrl) {
    stopSocketsForOtherOrigins();
  }
});

async function boot() {
  await refreshSettings();
  createContextMenus();
  if (settings.serverUrl && settings.apiToken) {
    try {
      await fetchStatus();
    } catch (err) {
      console.warn('Startup status failed:', formatCaughtError(err));
    }
    await reconcileActiveJobs();
    if (hasActiveJobs()) startReconcileLoop();
  }
}

chrome.runtime.onInstalled.addListener(() => {
  boot().catch((err) => console.error('onInstalled boot failed:', err));
});

chrome.runtime.onStartup.addListener(() => {
  boot().catch((err) => console.error('onStartup boot failed:', err));
});

  return boot().catch((err) => console.error('Eager boot failed:', err));
}

if (globalThis.chrome?.runtime?.id && !globalThis.__REELDOCK_TEST__) {
  startBackground();
}
