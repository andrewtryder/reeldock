/** Authoritative extension connection-state derivation. */

import { isDeviceToken } from './pairing.js';
import { normalizeAndValidateServerUrl } from './settings.js';

export const CONNECTION_STATES = Object.freeze({
  unconfigured: 'unconfigured',
  pairing: 'pairing',
  connected: 'connected',
  unreachable: 'unreachable',
  revoked: 'revoked',
  authentication_error: 'authentication_error',
  server_too_old: 'server_too_old',
  server_changed: 'server_changed',
});

export function formatLastConnected(timestampMs, nowMs = Date.now()) {
  if (!timestampMs || typeof timestampMs !== 'number') return '';
  const delta = Math.max(0, nowMs - timestampMs);
  if (delta < 15_000) return 'Just now';
  const seconds = Math.floor(delta / 1000);
  if (seconds < 60) return `${seconds} seconds ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return minutes === 1 ? '1 minute ago' : `${minutes} minutes ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return hours === 1 ? '1 hour ago' : `${hours} hours ago`;
  const days = Math.floor(hours / 24);
  return days === 1 ? '1 day ago' : `${days} days ago`;
}

/**
 * Derive a single connection state for Options and popup.
 *
 * @param {{
 *   settings?: Record<string, unknown>,
 *   status?: Record<string, unknown> | null,
 *   capabilities?: { ready?: boolean, apiVersion?: number, legacyMessage?: string } | null,
 *   connectionError?: string,
 *   httpStatus?: number | null,
 *   pairingInFlight?: boolean,
 *   nowMs?: number,
 * }} input
 */
export function deriveConnectionState(input = {}) {
  const settings = input.settings || {};
  const status = input.status || null;
  const capabilities = input.capabilities || null;
  const connectionError = String(input.connectionError || '');
  const httpStatus = input.httpStatus ?? null;
  const pairingInFlight = Boolean(input.pairingInFlight);
  const nowMs = input.nowMs ?? Date.now();

  const originCheck = normalizeAndValidateServerUrl(settings.serverUrl || '');
  const hasCredential = Boolean(settings.apiToken);
  const deviceCredential = isDeviceToken(settings.apiToken || '');
  const lastConnectedAt = Number(settings.lastConnectedAt) || 0;
  const pairedInstanceId = String(settings.pairedServerInstanceId || '');
  const remoteInstanceId = status?.instance_id ? String(status.instance_id) : '';
  const lastConnectedLabel = formatLastConnected(lastConnectedAt, nowMs);

  const base = {
    origin: originCheck.ok ? originCheck.origin : '',
    originError: originCheck.ok ? '' : originCheck.error,
    hasCredential,
    deviceCredential,
    deviceName: String(settings.deviceName || ''),
    deviceId: String(settings.deviceId || ''),
    apiVersion: capabilities?.apiVersion || status?.api_version || 0,
    lastConnectedAt,
    lastConnectedLabel,
    pairedServerInstanceId: pairedInstanceId,
    remoteInstanceId,
    legacyMessage: capabilities?.legacyMessage || '',
    message: '',
    actionLabel: '',
  };

  if (pairingInFlight) {
    return {
      ...base,
      state: CONNECTION_STATES.pairing,
      message: 'Pairing…',
      actionLabel: '',
    };
  }

  if (!originCheck.ok || !hasCredential) {
    return {
      ...base,
      state: CONNECTION_STATES.unconfigured,
      message: 'Pair this browser with your ReelDock server before creating audiobooks.',
      actionLabel: 'Open connection setup',
    };
  }

  if (httpStatus === 401 || /not authorized|no longer paired|401/i.test(connectionError)) {
    if (deviceCredential) {
      return {
        ...base,
        state: CONNECTION_STATES.revoked,
        message: 'This browser is no longer paired with ReelDock. Pair it again from ReelDock Settings.',
        actionLabel: 'Pair again',
      };
    }
    return {
      ...base,
      state: CONNECTION_STATES.authentication_error,
      message: connectionError || 'Not authorized. Pair this browser, or paste a legacy token under Advanced.',
      actionLabel: 'Open connection setup',
    };
  }

  if (connectionError || (httpStatus != null && httpStatus >= 500)) {
    return {
      ...base,
      state: CONNECTION_STATES.unreachable,
      message: lastConnectedLabel
        ? `ReelDock is unavailable. Last connected ${lastConnectedLabel}.`
        : 'ReelDock is unavailable.',
      actionLabel: 'Retry',
    };
  }

  if (status && pairedInstanceId && remoteInstanceId && pairedInstanceId !== remoteInstanceId) {
    return {
      ...base,
      state: CONNECTION_STATES.server_changed,
      message: 'This address now points to a different ReelDock server.',
      actionLabel: 'Pair with this server',
    };
  }

  if (capabilities && capabilities.ready === false) {
    return {
      ...base,
      state: CONNECTION_STATES.server_too_old,
      message:
        capabilities.legacyMessage ||
        'This ReelDock server does not support all features in this extension.',
      actionLabel: 'Open Settings',
    };
  }

  if (status) {
    return {
      ...base,
      state: CONNECTION_STATES.connected,
      message: 'Connected to ReelDock',
      actionLabel: 'Test connection',
      deviceName: String(status.device_name || settings.deviceName || ''),
      deviceId: String(status.device_id || settings.deviceId || ''),
      apiVersion: Number(status.api_version || capabilities?.apiVersion || 1),
    };
  }

  if (lastConnectedAt) {
    return {
      ...base,
      state: CONNECTION_STATES.unreachable,
      message: `ReelDock is unavailable. Last connected ${lastConnectedLabel}.`,
      actionLabel: 'Retry',
    };
  }

  return {
    ...base,
    state: CONNECTION_STATES.unconfigured,
    message: 'Pair this browser with your ReelDock server before creating audiobooks.',
    actionLabel: 'Open connection setup',
  };
}

export function connectionBadge(state) {
  switch (state) {
    case CONNECTION_STATES.connected:
      return { symbol: '●', label: 'Connected', tone: 'ok' };
    case CONNECTION_STATES.unreachable:
      return { symbol: '○', label: 'ReelDock unavailable', tone: 'err' };
    case CONNECTION_STATES.revoked:
    case CONNECTION_STATES.authentication_error:
      return { symbol: '✕', label: 'Pair this browser again', tone: 'err' };
    case CONNECTION_STATES.server_changed:
      return { symbol: '○', label: 'Different ReelDock server', tone: 'err' };
    case CONNECTION_STATES.server_too_old:
      return { symbol: '○', label: 'Update ReelDock', tone: 'err' };
    case CONNECTION_STATES.pairing:
      return { symbol: '◌', label: 'Pairing…', tone: 'pending' };
    default:
      return { symbol: '○', label: 'Connect ReelDock', tone: 'err' };
  }
}
