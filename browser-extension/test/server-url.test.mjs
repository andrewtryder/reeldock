import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import {
  HTTPS_REQUIRED_ERROR,
  isLocalServerUrl,
  normalizeAndValidateServerUrl,
  optionalHostPermissionPattern,
  requireValidatedServerOrigin,
} from '../src/settings.js';

describe('normalizeAndValidateServerUrl', () => {
  const pass = [
    ['http://localhost:8080', 'http://localhost:8080'],
    ['https://localhost:8443', 'https://localhost:8443'],
    ['http://127.0.0.1:8080', 'http://127.0.0.1:8080'],
    ['http://127.0.0.1:8080/', 'http://127.0.0.1:8080'],
    ['https://192.168.1.20', 'https://192.168.1.20'],
    ['https://reeldock.example.com', 'https://reeldock.example.com'],
    ['https://reeldock.example.com:8443', 'https://reeldock.example.com:8443'],
    ['http://[::1]:8080', 'http://[::1]:8080'],
    ['https://[::1]', 'https://[::1]'],
  ];

  for (const [input, origin] of pass) {
    it(`accepts ${input}`, () => {
      const result = normalizeAndValidateServerUrl(input);
      assert.equal(result.ok, true);
      assert.equal(result.origin, origin);
      assert.equal(result.error, '');
      assert.equal(requireValidatedServerOrigin(input), origin);
    });
  }

  it('rejects non-loopback HTTP LAN', () => {
    const result = normalizeAndValidateServerUrl('http://192.168.1.20:8080');
    assert.equal(result.ok, false);
    assert.equal(result.error, HTTPS_REQUIRED_ERROR);
  });

  it('rejects non-loopback HTTP hostname', () => {
    const result = normalizeAndValidateServerUrl('http://reeldock.example.com');
    assert.equal(result.ok, false);
    assert.equal(result.error, HTTPS_REQUIRED_ERROR);
  });

  it('rejects ftp', () => {
    const result = normalizeAndValidateServerUrl('ftp://reeldock.example.com');
    assert.equal(result.ok, false);
    assert.match(result.error, /http:\/\/ or https:\/\//);
  });

  it('rejects file', () => {
    const result = normalizeAndValidateServerUrl('file:///etc/passwd');
    assert.equal(result.ok, false);
  });

  it('rejects chrome and moz-extension schemes', () => {
    assert.equal(normalizeAndValidateServerUrl('chrome://extensions').ok, false);
    assert.equal(normalizeAndValidateServerUrl('moz-extension://abc/options.html').ok, false);
  });

  it('rejects malformed values', () => {
    assert.equal(normalizeAndValidateServerUrl('not a url').ok, false);
    assert.equal(normalizeAndValidateServerUrl('localhost:8080').ok, false);
    assert.equal(normalizeAndValidateServerUrl('').ok, false);
  });

  it('rejects embedded userinfo', () => {
    const result = normalizeAndValidateServerUrl('https://user:pass@reeldock.example.com');
    assert.equal(result.ok, false);
    assert.match(result.error, /username or password/);
  });

  it('rejects query string', () => {
    const result = normalizeAndValidateServerUrl('https://reeldock.example.com/?next=/');
    assert.equal(result.ok, false);
    assert.match(result.error, /query string or fragment/);
  });

  it('rejects fragment', () => {
    const result = normalizeAndValidateServerUrl('https://reeldock.example.com/#opts');
    assert.equal(result.ok, false);
    assert.match(result.error, /query string or fragment/);
  });

  it('rejects unexpected path', () => {
    const result = normalizeAndValidateServerUrl('https://reeldock.example.com/reeldock');
    assert.equal(result.ok, false);
    assert.match(result.error, /origin only/);
  });
});

describe('optional host permission', () => {
  it('is derived from the normalized origin, not the raw input', () => {
    const { origin } = normalizeAndValidateServerUrl('https://reeldock.example.com:8443/');
    assert.equal(origin, 'https://reeldock.example.com:8443');
    assert.equal(
      optionalHostPermissionPattern(origin),
      'https://reeldock.example.com:8443/*',
    );
  });

  it('does not treat HTTPS LAN as local (permission still required)', () => {
    assert.equal(isLocalServerUrl('https://192.168.1.20'), false);
    assert.equal(isLocalServerUrl('http://127.0.0.1:8080'), true);
    assert.equal(isLocalServerUrl('http://[::1]:8080'), true);
  });
});
