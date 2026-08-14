import { connectionBadge, deriveConnectionState } from './connection-state.js';
import { DEFAULT_DEVICE_NAME, pairWithOrigin } from './pairing.js';
import {
  loadSettings,
  saveSettings,
  ensureServerHostPermission,
  normalizeAndValidateServerUrl,
} from './settings.js';

function $(id) {
  return document.getElementById(id);
}

function setHidden(id, hidden) {
  $(id)?.classList.toggle('hidden', hidden);
}

let cachedSettings = null;
let pairingInFlight = false;
let lastPublicState = null;

function populate(settings) {
  cachedSettings = settings;
  $('serverUrl').value = settings.serverUrl || '';
  // Never surface the credential into the visible/legacy field when it is a device token.
  $('apiToken').value = settings.apiToken && !String(settings.apiToken).startsWith('rdx_')
    ? settings.apiToken
    : '';
  if ($('deviceName')) {
    $('deviceName').value = settings.deviceName || DEFAULT_DEVICE_NAME;
  }
  if ($('pairingCode')) {
    $('pairingCode').value = '';
  }
  $('defaultDestinationFolder').value = settings.defaultDestinationFolder || '';
  $('defaultQuality').value = settings.defaultQuality || 'standard';
  $('embedMetadata').checked = settings.embedMetadata;
  $('embedThumbnail').checked = settings.embedThumbnail;
  $('embedChapters').checked = settings.embedChapters;
  $('sponsorblockRemove').checked = Boolean(settings.sponsorblockRemove);
  $('triggerAbsScan').checked = settings.triggerAbsScan;
  $('allowReimport').checked = settings.allowReimport;
  $('openReelDockAfterQueue').checked = Boolean(settings.openReelDockAfterQueue);
  markQuality(settings.defaultQuality || 'standard');
}

function markQuality(quality) {
  $('defaultQuality').value = quality;
  for (const button of document.querySelectorAll('[data-quality]')) {
    button.classList.toggle('active', button.dataset.quality === quality);
  }
}

function collectDefaults() {
  const destinationSelect = $('destinationSelect');
  const destinationFromSelect =
    !$('destination-select-wrap').classList.contains('hidden') && destinationSelect
      ? destinationSelect.value
      : $('defaultDestinationFolder').value.trim();
  return {
    defaultDestinationFolder: destinationFromSelect,
    defaultQuality: $('defaultQuality').value || 'standard',
    embedMetadata: $('embedMetadata').checked,
    embedThumbnail: $('embedThumbnail').checked,
    embedChapters: $('embedChapters').checked,
    sponsorblockRemove: $('sponsorblockRemove').checked,
    triggerAbsScan: $('triggerAbsScan').checked,
    allowReimport: $('allowReimport').checked,
    openReelDockAfterQueue: $('openReelDockAfterQueue').checked,
  };
}

function setStatus(text, ok = true) {
  const el = $('status');
  el.textContent = text;
  el.className = ok ? 'ok' : 'err';
}

function renderConnectionSummary(connection) {
  const el = $('connection-summary');
  if (!el || !connection) return;
  const badge = connectionBadge(connection.state);
  el.className = `connection-summary ${badge.tone === 'ok' ? 'ok' : badge.tone === 'err' ? 'err' : ''}`;
  el.replaceChildren();
  const title = document.createElement('div');
  title.textContent = `${badge.symbol} ${badge.label}`;
  el.appendChild(title);
  if (connection.message) {
    const msg = document.createElement('div');
    msg.className = 'meta';
    msg.textContent = connection.message;
    el.appendChild(msg);
  }
  if (connection.state === 'connected') {
    const meta = document.createElement('div');
    meta.className = 'meta';
    const parts = [
      connection.origin,
      connection.deviceName ? `Device: ${connection.deviceName}` : '',
      connection.apiVersion ? `API v${connection.apiVersion}` : '',
      connection.lastConnectedLabel ? `Last checked ${connection.lastConnectedLabel}` : '',
    ].filter(Boolean);
    meta.textContent = parts.join(' · ');
    el.appendChild(meta);
  }
}

function applyConnectionLayout(connection) {
  const connected = connection?.state === 'connected';
  const pairing = connection?.state === 'pairing';
  setHidden('import-defaults-group', !connected);
  setHidden('pair-fields', connected);
  setHidden('connected-actions', !connected);
  $('serverUrl').readOnly = connected || pairing;
  if ($('pair')) $('pair').disabled = pairing;
  renderConnectionSummary(connection);
}

function applyCapabilities(payload) {
  const capabilities = payload?.capabilities;
  const ready = Boolean(capabilities?.ready);
  const supports = capabilities?.supports || {};
  const status = payload?.status || {};
  const destinations = payload?.destinations;

  setHidden('legacy-banner', ready || !payload?.configured);
  setHidden('quality-wrap', !supports.quality_presets);
  setHidden('sponsorblock-row', !supports.sponsorblock);
  setHidden('abs-row', !status.abs_configured);
  setHidden('destination-select-wrap', !supports.destinations);
  setHidden('destination-text-wrap', Boolean(supports.destinations));

  const destBanner = $('dest-banner');
  if (destinations?.banner) {
    destBanner.textContent = destinations.banner;
    destBanner.classList.remove('hidden');
  } else {
    destBanner.textContent = '';
    destBanner.classList.add('hidden');
  }

  if (supports.destinations && destinations?.choices) {
    const select = $('destinationSelect');
    select.replaceChildren();
    for (const choice of destinations.choices) {
      const option = document.createElement('option');
      option.value = choice.value;
      option.textContent = choice.label;
      select.appendChild(option);
    }
    select.value = destinations.selected ?? '';
    $('defaultDestinationFolder').value = destinations.selected ?? '';
  }
}

function validatedServerOriginOrStatus(serverUrl) {
  const result = normalizeAndValidateServerUrl(serverUrl);
  if (!result.ok) {
    setStatus(result.error, false);
    return null;
  }
  return result.origin;
}

async function requestHostPermission(serverUrl) {
  const granted = await ensureServerHostPermission(serverUrl);
  if (!granted) {
    setStatus('Host permission is required for this ReelDock server URL.', false);
    return false;
  }
  return true;
}

function connectionFromPublic(res, settingsOverride = null) {
  return (
    res?.connectionState ||
    deriveConnectionState({
      settings: settingsOverride || res?.settings || cachedSettings || {},
      status: res?.status,
      capabilities: res?.capabilities,
      connectionError: res?.connectionError,
      httpStatus: res?.httpStatus,
      pairingInFlight,
    })
  );
}

async function refreshView() {
  const settings = await loadSettings();
  cachedSettings = settings;
  populate(settings);
  let res = null;
  try {
    res = await chrome.runtime.sendMessage({ action: 'getPublicState' });
    lastPublicState = res;
  } catch {
    res = null;
  }
  const connection = connectionFromPublic(res, settings);
  applyConnectionLayout(connection);
  if (res?.ok) applyCapabilities(res);
  return { settings, res, connection };
}

async function onPair() {
  try {
    const serverUrl = $('serverUrl').value.trim();
    const pairingCode = $('pairingCode').value;
    const deviceName = $('deviceName')?.value.trim() || DEFAULT_DEVICE_NAME;
    if (!validatedServerOriginOrStatus(serverUrl)) return;
    if (!(await requestHostPermission(serverUrl))) return;
    pairingInFlight = true;
    applyConnectionLayout(deriveConnectionState({ settings: cachedSettings, pairingInFlight: true }));
    setStatus('Pairing…', true);
    const paired = await pairWithOrigin({ serverUrl, pairingCode, deviceName });
    const current = await loadSettings();
    await saveSettings({
      ...current,
      ...collectDefaults(),
      serverUrl: paired.origin,
      apiToken: paired.deviceToken,
      deviceId: paired.deviceId,
      deviceName,
      pairedServerInstanceId: '',
    });
    $('pairingCode').value = '';
    $('apiToken').value = '';
    setStatus('Paired. Testing connection…', true);
    await onTest();
  } catch (err) {
    setStatus(err.message || 'Pairing failed', false);
  } finally {
    pairingInFlight = false;
    await refreshView();
  }
}

async function onDisconnect() {
  try {
    const res = await chrome.runtime.sendMessage({ action: 'revokeDevice' });
    if (!res?.ok) throw new Error(res?.error || 'Disconnect failed');
    $('apiToken').value = '';
    if ($('pairingCode')) $('pairingCode').value = '';
    setStatus('Disconnected. Pair again to reconnect.', true);
    await refreshView();
  } catch (err) {
    setStatus(err.message || 'Disconnect failed', false);
  }
}

async function onChangeServer() {
  const dialog = $('change-server-dialog');
  if (!dialog?.showModal) {
    if (!window.confirm('Change server disconnects this browser from the current ReelDock instance. Continue?')) {
      return;
    }
  } else {
    const result = await new Promise((resolve) => {
      const onClose = () => {
        dialog.removeEventListener('close', onClose);
        resolve(dialog.returnValue);
      };
      dialog.addEventListener('close', onClose);
      dialog.returnValue = 'cancel';
      dialog.showModal();
    });
    if (result !== 'confirm') return;
  }

  const revoke = await chrome.runtime.sendMessage({ action: 'revokeDevice' });
  if (!revoke?.ok) {
    setStatus(
      `${revoke?.error || 'Could not revoke on the server.'} You can disconnect locally without revoking.`,
      false,
    );
    const localBtn = document.createElement('button');
    localBtn.type = 'button';
    localBtn.textContent = 'Disconnect locally without revoking';
    localBtn.id = 'disconnect-local-once';
    localBtn.addEventListener(
      'click',
      async () => {
        const local = await chrome.runtime.sendMessage({ action: 'disconnectLocal' });
        if (!local?.ok) {
          setStatus(local?.error || 'Local disconnect failed', false);
          return;
        }
        setStatus('Disconnected locally. The server device token was not revoked.', true);
        await refreshView();
      },
      { once: true },
    );
    const status = $('status');
    status.after(localBtn);
    return;
  }
  $('serverUrl').value = '';
  $('apiToken').value = '';
  if ($('pairingCode')) $('pairingCode').value = '';
  const current = await loadSettings();
  await saveSettings({
    ...current,
    serverUrl: '',
    apiToken: '',
    deviceId: '',
    pairedServerInstanceId: '',
    lastConnectedAt: 0,
  });
  setStatus('Enter the new ReelDock origin and pair again.', true);
  await refreshView();
}

async function onSaveDefaults() {
  try {
    const current = await loadSettings();
    if (!current.apiToken) {
      setStatus('Connect this browser before saving import defaults.', false);
      return;
    }
    await saveSettings({ ...current, ...collectDefaults() });
    setStatus('Import defaults saved.', true);
    await refreshView();
  } catch (err) {
    setStatus(`Save failed: ${err.message}`, false);
  }
}

async function onSaveLegacy() {
  try {
    const serverUrl = $('serverUrl').value.trim();
    const apiToken = $('apiToken').value.trim();
    if (!validatedServerOriginOrStatus(serverUrl)) return;
    if (!(await requestHostPermission(serverUrl))) return;
    if (!apiToken) {
      setStatus('Paste a legacy token, or use Connect with a pairing code.', false);
      return;
    }
    const current = await loadSettings();
    await saveSettings({
      ...current,
      ...collectDefaults(),
      serverUrl,
      apiToken,
      deviceId: '',
      pairedServerInstanceId: '',
    });
    setStatus('Legacy token saved. Testing connection…', true);
    await onTest();
  } catch (err) {
    setStatus(`Save failed: ${err.message}`, false);
  }
}

async function onTest() {
  const settings = await loadSettings();
  const serverUrl = $('serverUrl').value.trim() || settings.serverUrl;
  const apiToken = settings.apiToken || $('apiToken').value.trim();
  if (!validatedServerOriginOrStatus(serverUrl)) return;
  if (!(await requestHostPermission(serverUrl))) return;
  if (!apiToken) {
    setStatus('Connect this browser before testing.', false);
    return;
  }
  setStatus('Testing connection…', true);
  try {
    const res = await chrome.runtime.sendMessage({
      action: 'testConnection',
      serverUrl,
      apiToken,
    });
    if (!res?.ok) throw new Error(res?.error || 'Connection failed');
    lastPublicState = res;
    applyCapabilities({ ...res, configured: true });
    const connection = connectionFromPublic(res, {
      ...settings,
      serverUrl,
      apiToken,
      pairedServerInstanceId: settings.pairedServerInstanceId,
    });
    applyConnectionLayout(connection);
    if (connection.state === 'connected') {
      setStatus('Connected successfully!', true);
    } else {
      setStatus(connection.message || 'Server responded but not connected', false);
    }
    await refreshView();
  } catch (err) {
    setStatus(err.message || 'Connection failed', false);
    await refreshView();
  }
}

export async function startOptions() {
  for (const button of document.querySelectorAll('[data-quality]')) {
    button.addEventListener('click', (event) => {
      event.preventDefault();
      markQuality(button.dataset.quality);
    });
  }

  $('save')?.addEventListener('click', onSaveDefaults);
  $('save-legacy')?.addEventListener('click', onSaveLegacy);
  $('test')?.addEventListener('click', onTest);
  $('pair')?.addEventListener('click', onPair);
  $('disconnect')?.addEventListener('click', onDisconnect);
  $('change-server')?.addEventListener('click', onChangeServer);
  const { connection } = await refreshView();
  if (document.documentElement) {
    document.documentElement.dataset.reeldockReady = '1';
  }
  if (connection?.state === 'connected' || connection?.hasCredential) {
    // refreshView already applied capabilities when public state was available.
  }
}

if (globalThis.chrome?.runtime?.id && !globalThis.__REELDOCK_TEST__) {
  startOptions();
}
