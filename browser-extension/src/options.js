import {
  loadSettings,
  saveSettings,
  ensureServerHostPermission,
  normalizeAndValidateServerUrl,
  requireValidatedServerOrigin,
} from './settings.js';

function $(id) { return document.getElementById(id); }

function populate(settings) {
  $('serverUrl').value = settings.serverUrl || '';
  $('apiToken').value = settings.apiToken || '';
  $('defaultDestinationFolder').value = settings.defaultDestinationFolder || '';
  $('embedMetadata').checked = settings.embedMetadata;
  $('embedThumbnail').checked = settings.embedThumbnail;
  $('embedChapters').checked = settings.embedChapters;
  $('triggerAbsScan').checked = settings.triggerAbsScan;
  $('allowReimport').checked = settings.allowReimport;
}

function collect() {
  return {
    serverUrl: $('serverUrl').value.trim(),
    apiToken: $('apiToken').value.trim(),
    defaultDestinationFolder: $('defaultDestinationFolder').value.trim(),
    embedMetadata: $('embedMetadata').checked,
    embedThumbnail: $('embedThumbnail').checked,
    embedChapters: $('embedChapters').checked,
    triggerAbsScan: $('triggerAbsScan').checked,
    allowReimport: $('allowReimport').checked,
  };
}

function setStatus(text, ok = true) {
  const el = $('status');
  el.textContent = text;
  el.className = ok ? 'ok' : 'err';
}

function updateStatusPanel(statusData, settings) {
  // Status panel elements
  const statusIndicator = document.getElementById('status-indicator');
  const statusText = document.getElementById('status-text');
  const connectionStatus = document.getElementById('connection-status');
  const dryRunStatus = document.getElementById('dry-run-status');
  const absConfigured = document.getElementById('abs-configured');
  const playlistsAllowed = document.getElementById('playlists-allowed');
  const channelsAllowed = document.getElementById('channels-allowed');
  const apiStatus = document.getElementById('api-status');

  // Update connection status indicator
  if (statusData.extension_api_enabled && statusData.auth_required) {
    statusIndicator.className = 'status-indicator status-connected';
    statusIndicator.title = 'Extension API enabled with token required';
    connectionStatus.textContent = 'Connected';
    apiStatus.textContent = 'API Auth Required';
    apiStatus.className = 'status-badge status-warning';
  } else if (statusData.extension_api_enabled && !statusData.auth_required) {
    statusIndicator.className = 'status-indicator status-connected';
    statusIndicator.title = 'Extension API enabled without token';
    connectionStatus.textContent = 'Connected';
    apiStatus.textContent = 'API No Auth';
    apiStatus.className = 'status-badge status-success';
  } else {
    statusIndicator.className = 'status-indicator status-disconnected';
    statusIndicator.title = 'Extension API disabled';
    connectionStatus.textContent = 'Disconnected';
    apiStatus.textContent = 'API Disabled';
    apiStatus.className = 'status-badge status-error';
  }

  // Update dry run status
  dryRunStatus.textContent = statusData.dry_run ? 'Dry run enabled' : 'Production mode';
  dryRunStatus.className = `status-badge ${statusData.dry_run ? 'status-warning' : 'status-success'}`;

  // Update ABS configured status
  const isAbsConfigured = statusData.abs_configured;
  absConfigured.textContent = isAbsConfigured ? 'Configured' : 'Not configured';
  absConfigured.className = `status-badge ${isAbsConfigured ? 'status-success' : 'status-error'}`;

  // Update playlists allowed
  playlistsAllowed.textContent = statusData.allow_playlists ? 'Allowed' : 'Restricted';
  playlistsAllowed.className = `status-badge ${statusData.allow_playlists ? 'status-success' : 'status-error'}`;

  // Update channels allowed
  channelsAllowed.textContent = statusData.allow_channels ? 'Allowed' : 'Restricted';
  channelsAllowed.className = `status-badge ${statusData.allow_channels ? 'status-success' : 'status-error'}`;

  // Update overall status
  let overallStatus = 'OK';
  let overallClass = 'status-success';

  if (!statusData.extension_api_enabled) {
    overallStatus = 'API Disabled';
    overallClass = 'status-error';
  } else if (statusData.extension_api_enabled && statusData.auth_required && !statusData.ok) {
    overallStatus = 'Invalid Token';
    overallClass = 'status-error';
  } else if (statusData.dry_run) {
    overallStatus = 'Dry Run';
    overallClass = 'status-warning';
  } else {
    overallStatus = 'Production';
    overallClass = 'status-success';
  }

  document.getElementById('overall-status').textContent = overallStatus;
  document.getElementById('overall-status-indicator').className = `status-indicator ${overallClass}`;
}

function validatedServerOriginOrStatus(serverUrl) {
  const result = normalizeAndValidateServerUrl(serverUrl);
  if (!result.ok) {
    setStatus(result.error, false);
    return null;
  }
  return result.origin;
}

async function loadStatusFromServer(serverUrl, apiToken = null) {
  const base = requireValidatedServerOrigin(serverUrl);
  try {
    const headers = {};
    if (apiToken) headers['Authorization'] = `Bearer ${apiToken}`;

    const res = await fetch(`${base}/api/extension/status`, { headers });
    if (!res.ok) {
      throw new Error(`HTTP ${res.status}`);
    }

    return await res.json();
  } catch (err) {
    throw new Error(`Failed to load server status: ${err.message}`);
  }
}

async function requestHostPermission(serverUrl) {
  const granted = await ensureServerHostPermission(serverUrl);
  if (!granted) {
    setStatus('Host permission is required for this ReelDock server URL.', false);
    return false;
  }
  return true;
}

async function onSave() {
  try {
    const settings = collect();
    if (!validatedServerOriginOrStatus(settings.serverUrl)) {
      return;
    }
    if (!(await requestHostPermission(settings.serverUrl))) {
      return;
    }
    if (!settings.apiToken) {
      setStatus('API token is required (server requires EXTENSION_API_TOKEN).', false);
      return;
    }
    await saveSettings(settings);

    // Refresh status after saving
    setStatus('Settings saved, testing connection...', true);
    await onTest();
  } catch (err) {
    setStatus(`Save failed: ${err.message}`, false);
  }
}

async function onTest() {
  const { serverUrl, apiToken } = collect();

  if (!validatedServerOriginOrStatus(serverUrl)) {
    return;
  }

  if (!(await requestHostPermission(serverUrl))) {
    return;
  }

  setStatus('Testing connection…', true);
  // Keep the detailed status panel hidden by default.
  document.getElementById('status-panel').style.display = 'none';

  try {
    const statusData = await loadStatusFromServer(serverUrl, apiToken);
    const showDetailedStatus = !statusData.ok;
    if (showDetailedStatus) {
      // Only show detailed status when there is a problem.
      updateStatusPanel(statusData, collect());
      document.getElementById('status-panel').style.display = 'block';
    } else {
      document.getElementById('status-panel').style.display = 'none';
    }

    setStatus(statusData.ok ? 'Connected successfully!' : 'Server responded but not OK', statusData.ok ? true : false);

  } catch (err) {
    console.error('Test connection failed:', err);

    // Hide status panel on error
    document.getElementById('status-panel').style.display = 'none';

    setStatus(`Connection failed: ${err.message}`, false);
  }
}

(async () => {
  populate(await loadSettings());
  $('save').addEventListener('click', onSave);
  $('test').addEventListener('click', onTest);

  // Optional: Auto-test on page load if server URL is configured
  const initialSettings = await loadSettings();
  if (normalizeAndValidateServerUrl(initialSettings.serverUrl).ok) {
    // Small delay to allow page render
    setTimeout(async () => {
      try {
        const statusData = await loadStatusFromServer(
          initialSettings.serverUrl,
          initialSettings.apiToken
        );
        if (!statusData.ok) {
          updateStatusPanel(statusData, initialSettings);
          document.getElementById('status-panel').style.display = 'block';
        } else {
          document.getElementById('status-panel').style.display = 'none';
        }
        setStatus('Connection status loaded', true);
      } catch (err) {
        console.log('Initial status load failed:', err);
        document.getElementById('status-panel').style.display = 'none';
      }
    }, 500);
  }
})();
