import { requireValidatedServerOrigin } from './settings.js';

export const DEFAULT_DEVICE_NAME = 'This browser';

export function normalizePairingCode(raw) {
  const compact = String(raw || '')
    .trim()
    .toUpperCase()
    .replace(/[^A-Z0-9-]/g, '');
  if (compact.startsWith('RDK') && !compact.includes('-', 3) && compact.length === 11) {
    return `RDK-${compact.slice(3, 7)}-${compact.slice(7)}`;
  }
  return compact;
}

export function isDeviceToken(token) {
  return typeof token === 'string' && token.startsWith('rdx_');
}

export async function pairWithOrigin({ serverUrl, pairingCode, deviceName, fetchImpl = fetch }) {
  const origin = requireValidatedServerOrigin(serverUrl);
  const code = normalizePairingCode(pairingCode);
  if (!code.startsWith('RDK-')) {
    throw new Error('Enter the pairing code from ReelDock Settings.');
  }
  const response = await fetchImpl(`${origin}/api/extension/pair`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      pairing_code: code,
      device_name: (deviceName || DEFAULT_DEVICE_NAME).trim() || DEFAULT_DEVICE_NAME,
    }),
  });
  let payload = {};
  try {
    payload = await response.json();
  } catch {
    payload = {};
  }
  if (!response.ok) {
    const detail = payload?.detail || `Pairing failed (HTTP ${response.status})`;
    throw new Error(typeof detail === 'string' ? detail : 'Pairing failed');
  }
  if (!payload.device_token || !payload.device_id) {
    throw new Error('Pairing response was missing a device token.');
  }
  return {
    origin,
    deviceId: payload.device_id,
    deviceToken: payload.device_token,
    instanceId: payload.instance_id ? String(payload.instance_id) : '',
    apiVersion: payload.api_version,
    supports: payload.supports || {},
  };
}

export async function applyDeviceRevoke({ isDevice, revokeRemote, clearLocal }) {
  if (!isDevice) {
    await clearLocal();
    return { ok: true, status: 'disconnected' };
  }
  await revokeRemote();
  await clearLocal();
  return { ok: true, status: 'revoked' };
}
