import assert from 'node:assert/strict';
import test from 'node:test';

import {
  CONNECTION_STATES,
  connectionBadge,
  deriveConnectionState,
  formatLastConnected,
} from '../src/connection-state.js';

const baseSettings = {
  serverUrl: 'http://127.0.0.1:8080',
  apiToken: 'rdx_device_token_example',
  deviceName: 'Chrome on MacBook',
  deviceId: 'dev-1',
  pairedServerInstanceId: 'inst-a',
  lastConnectedAt: Date.now() - 60_000,
};

test('formatLastConnected covers relative buckets', () => {
  const now = 1_700_000_000_000;
  assert.equal(formatLastConnected(now - 5_000, now), 'Just now');
  assert.equal(formatLastConnected(now - 30_000, now), '30 seconds ago');
  assert.equal(formatLastConnected(now - 120_000, now), '2 minutes ago');
  assert.equal(formatLastConnected(now - 3_600_000, now), '1 hour ago');
  assert.equal(formatLastConnected(now - 90_000_000, now), '1 day ago');
  assert.equal(formatLastConnected(0, now), '');
});

test('unconfigured when origin or credential missing', () => {
  assert.equal(
    deriveConnectionState({ settings: { serverUrl: '', apiToken: '' } }).state,
    CONNECTION_STATES.unconfigured,
  );
  assert.equal(
    deriveConnectionState({
      settings: { serverUrl: 'http://127.0.0.1:8080', apiToken: '' },
    }).state,
    CONNECTION_STATES.unconfigured,
  );
});

test('pairing in flight', () => {
  const state = deriveConnectionState({ settings: baseSettings, pairingInFlight: true });
  assert.equal(state.state, CONNECTION_STATES.pairing);
});

test('connected when status and capabilities ready', () => {
  const state = deriveConnectionState({
    settings: baseSettings,
    status: {
      ok: true,
      api_version: 1,
      instance_id: 'inst-a',
      device_name: 'Chrome on MacBook',
    },
    capabilities: { ready: true, apiVersion: 1 },
  });
  assert.equal(state.state, CONNECTION_STATES.connected);
  assert.match(state.lastConnectedLabel, /minute/);
});

test('server_changed when instance id mismatches', () => {
  const state = deriveConnectionState({
    settings: baseSettings,
    status: { ok: true, api_version: 1, instance_id: 'inst-b' },
    capabilities: { ready: true, apiVersion: 1 },
  });
  assert.equal(state.state, CONNECTION_STATES.server_changed);
});

test('server_too_old when capabilities not ready', () => {
  const state = deriveConnectionState({
    settings: baseSettings,
    status: { ok: true, instance_id: 'inst-a' },
    capabilities: { ready: false, legacyMessage: 'Update ReelDock' },
  });
  assert.equal(state.state, CONNECTION_STATES.server_too_old);
});

test('revoked vs authentication_error on 401', () => {
  assert.equal(
    deriveConnectionState({
      settings: baseSettings,
      httpStatus: 401,
      connectionError: 'Not authorized',
    }).state,
    CONNECTION_STATES.revoked,
  );
  assert.equal(
    deriveConnectionState({
      settings: { ...baseSettings, apiToken: 'legacy-shared-token' },
      httpStatus: 401,
      connectionError: 'Not authorized',
    }).state,
    CONNECTION_STATES.authentication_error,
  );
});

test('unreachable keeps pairing metadata', () => {
  const state = deriveConnectionState({
    settings: baseSettings,
    connectionError: 'Failed to fetch',
  });
  assert.equal(state.state, CONNECTION_STATES.unreachable);
  assert.equal(state.pairedServerInstanceId, 'inst-a');
  assert.match(state.message, /Last connected/);
});

test('connectionBadge vocabulary', () => {
  assert.equal(connectionBadge(CONNECTION_STATES.connected).label, 'Connected');
  assert.equal(connectionBadge(CONNECTION_STATES.unconfigured).label, 'Connect ReelDock');
  assert.equal(connectionBadge(CONNECTION_STATES.revoked).label, 'Pair this browser again');
});
