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

function populate(settings) {
  $('serverUrl').value = settings.serverUrl || '';
  $('apiToken').value = settings.apiToken || '';
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

function collect() {
  const destinationSelect = $('destinationSelect');
  const destinationFromSelect =
    !$('destination-select-wrap').classList.contains('hidden') && destinationSelect
      ? destinationSelect.value
      : $('defaultDestinationFolder').value.trim();
  return {
    serverUrl: $('serverUrl').value.trim(),
    apiToken: $('apiToken').value.trim(),
    deviceName: $('deviceName')?.value.trim() || DEFAULT_DEVICE_NAME,
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

function applyCapabilities(payload) {
  const capabilities = payload?.capabilities;
  const ready = Boolean(capabilities?.ready);
  const supports = capabilities?.supports || {};
  const status = payload?.status || {};
  const destinations = payload?.destinations;

  setHidden('legacy-banner', ready);
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

async function onPair() {
  try {
    const serverUrl = $('serverUrl').value.trim();
    const pairingCode = $('pairingCode').value;
    const deviceName = $('deviceName')?.value.trim() || DEFAULT_DEVICE_NAME;
    if (!validatedServerOriginOrStatus(serverUrl)) return;
    if (!(await requestHostPermission(serverUrl))) return;
    setStatus('Pairing…', true);
    const paired = await pairWithOrigin({ serverUrl, pairingCode, deviceName });
    const current = collect();
    await saveSettings({
      ...current,
      serverUrl: paired.origin,
      apiToken: paired.deviceToken,
      deviceId: paired.deviceId,
      deviceName,
    });
    $('pairingCode').value = '';
    $('apiToken').value = paired.deviceToken;
    setStatus('Paired. Testing connection…', true);
    await onTest();
  } catch (err) {
    setStatus(err.message || 'Pairing failed', false);
  }
}

async function onDisconnect() {
  try {
    const res = await chrome.runtime.sendMessage({ action: 'revokeDevice' });
    if (!res?.ok) throw new Error(res?.error || 'Disconnect failed');
    $('apiToken').value = '';
    if ($('pairingCode')) $('pairingCode').value = '';
    setStatus('Disconnected. Pair again to reconnect.', true);
  } catch (err) {
    setStatus(err.message || 'Disconnect failed', false);
  }
}

async function onDisconnectLocal() {
  try {
    const res = await chrome.runtime.sendMessage({ action: 'disconnectLocal' });
    if (!res?.ok) throw new Error(res?.error || 'Local disconnect failed');
    $('apiToken').value = '';
    if ($('pairingCode')) $('pairingCode').value = '';
    setStatus('Disconnected locally. The server device token was not revoked.', true);
  } catch (err) {
    setStatus(err.message || 'Local disconnect failed', false);
  }
}

async function onSave() {
  try {
    const settings = collect();
    if (!validatedServerOriginOrStatus(settings.serverUrl)) return;
    if (!(await requestHostPermission(settings.serverUrl))) return;
    if (!settings.apiToken) {
      setStatus('API token is required (server requires EXTENSION_API_TOKEN).', false);
      return;
    }
    await saveSettings(settings);
    setStatus('Settings saved, testing connection…', true);
    await onTest();
  } catch (err) {
    setStatus(`Save failed: ${err.message}`, false);
  }
}

async function onTest() {
  const { serverUrl, apiToken } = collect();
  if (!validatedServerOriginOrStatus(serverUrl)) return;
  if (!(await requestHostPermission(serverUrl))) return;
  if (!apiToken) {
    setStatus('API token is required.', false);
    return;
  }
  setStatus('Testing connection…', true);
  $('status-panel').style.display = 'none';
  try {
    const res = await chrome.runtime.sendMessage({
      action: 'testConnection',
      serverUrl,
      apiToken,
    });
    if (!res?.ok) throw new Error(res?.error || 'Connection failed');
    applyCapabilities(res);
    if (res.status && !res.status.ok) {
      updateStatusPanel(res.status);
      $('status-panel').style.display = 'block';
      setStatus('Server responded but not OK', false);
      return;
    }
    setStatus('Connected successfully!', true);
  } catch (err) {
    console.error('Test connection failed:', err);
    $('status-panel').style.display = 'none';
    setStatus(err.message || 'Connection failed', false);
  }
}

function updateStatusPanel(statusData) {
  const statusIndicator = $('status-indicator');
  const connectionStatus = $('connection-status');
  const dryRunStatus = $('dry-run-status');
  const absConfigured = $('abs-configured');
  const playlistsAllowed = $('playlists-allowed');
  const channelsAllowed = $('channels-allowed');
  const apiStatus = $('api-status');

  if (statusData.extension_api_enabled) {
    statusIndicator.className = 'status-indicator status-connected';
    connectionStatus.textContent = 'Connected';
    apiStatus.textContent = statusData.auth_required ? 'API Auth Required' : 'API No Auth';
    apiStatus.className = 'status-badge status-success';
  } else {
    statusIndicator.className = 'status-indicator status-disconnected';
    connectionStatus.textContent = 'Disconnected';
    apiStatus.textContent = 'API Disabled';
    apiStatus.className = 'status-badge status-error';
  }

  dryRunStatus.textContent = statusData.dry_run ? 'Dry run enabled' : 'Production mode';
  absConfigured.textContent = statusData.abs_configured ? 'Configured' : 'Not configured';
  playlistsAllowed.textContent = statusData.allow_playlists ? 'Allowed' : 'Restricted';
  channelsAllowed.textContent = statusData.allow_channels ? 'Allowed' : 'Restricted';
  $('overall-status').textContent = statusData.ok ? 'OK' : 'Not OK';
}

for (const button of document.querySelectorAll('[data-quality]')) {
  button.addEventListener('click', (event) => {
    event.preventDefault();
    markQuality(button.dataset.quality);
  });
}

(async () => {
  populate(await loadSettings());
  $('save').addEventListener('click', onSave);
  $('test').addEventListener('click', onTest);
  $('pair')?.addEventListener('click', onPair);
  $('disconnect')?.addEventListener('click', onDisconnect);
  $('disconnectLocal')?.addEventListener('click', onDisconnectLocal);

  const initial = await loadSettings();
  if (normalizeAndValidateServerUrl(initial.serverUrl).ok && initial.apiToken) {
    try {
      const res = await chrome.runtime.sendMessage({ action: 'getPublicState' });
      if (res?.ok) applyCapabilities(res);
    } catch (err) {
      console.log('Initial status load failed:', err);
    }
  }
})();
