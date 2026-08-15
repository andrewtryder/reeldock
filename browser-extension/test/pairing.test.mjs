import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import {
  DEFAULT_DEVICE_NAME,
  applyDeviceRevoke,
  isDeviceToken,
  normalizePairingCode,
  pairWithOrigin,
} from '../src/pairing.js';

describe('pairing helpers', () => {
  it('normalizes compact pairing codes', () => {
    assert.equal(normalizePairingCode('rdk-ab2d-efgh'), 'RDK-AB2D-EFGH');
    assert.equal(normalizePairingCode('RDKAB2DEFGH'), 'RDK-AB2D-EFGH');
  });

  it('detects device tokens', () => {
    assert.equal(isDeviceToken('rdx_abc'), true);
    assert.equal(isDeviceToken('legacy-shared'), false);
  });

  it('pairs, persists token fields, and does not keep the code', async () => {
    const calls = [];
    const fetchImpl = async (url, options) => {
      calls.push({ url, options });
      return {
        ok: true,
        json: async () => ({
          device_id: 'dev-1',
          device_token: 'rdx_deadbeef',
          instance_id: 'inst-a1b2',
          api_version: 1,
          supports: { destinations: true },
        }),
      };
    };
    const result = await pairWithOrigin({
      serverUrl: 'http://127.0.0.1:8080',
      pairingCode: 'rdk-ab2d-efgh',
      deviceName: 'Office Chrome',
      fetchImpl,
    });
    assert.equal(result.origin, 'http://127.0.0.1:8080');
    assert.equal(result.deviceToken, 'rdx_deadbeef');
    assert.equal(result.deviceId, 'dev-1');
    assert.equal(result.instanceId, 'inst-a1b2');
    const body = JSON.parse(calls[0].options.body);
    assert.equal(body.pairing_code, 'RDK-AB2D-EFGH');
    assert.equal(body.device_name, 'Office Chrome');
    assert.equal(DEFAULT_DEVICE_NAME, 'This browser');
  });

  it('does not clear the device token when server revoke fails', async () => {
    let cleared = false;
    await assert.rejects(
      () =>
        applyDeviceRevoke({
          isDevice: true,
          revokeRemote: async () => {
            throw new Error('HTTP 503');
          },
          clearLocal: async () => {
            cleared = true;
          },
        }),
      /HTTP 503/,
    );
    assert.equal(cleared, false);
  });

  it('clears local credentials after a successful revoke', async () => {
    let cleared = false;
    const result = await applyDeviceRevoke({
      isDevice: true,
      revokeRemote: async () => {},
      clearLocal: async () => {
        cleared = true;
      },
    });
    assert.equal(result.ok, true);
    assert.equal(result.status, 'revoked');
    assert.equal(cleared, true);
  });
});
