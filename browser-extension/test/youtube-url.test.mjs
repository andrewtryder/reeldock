import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import { isYouTubeWatchUrl, publicSettings } from '../src/settings.js';
import { isYouTubeVideoUrl } from '../src/ui.js';
import { formatApiError } from '../src/errors.js';

describe('YouTube URL check', () => {
  it('accepts real 11-12 character ids and reserved smoke ids', () => {
    assert.equal(isYouTubeWatchUrl('https://www.youtube.com/watch?v=jNQXAC9IVRw'), true);
    assert.equal(isYouTubeWatchUrl('https://youtu.be/jNQXAC9IVRw'), true);
    assert.equal(isYouTubeWatchUrl('https://www.youtube.com/watch?v=reeldockSmoke01'), true);
    assert.equal(isYouTubeWatchUrl('https://www.youtube.com/watch?v=reeldockSmokeFail01'), true);
    assert.equal(isYouTubeWatchUrl('https://www.youtube.com/watch?v=reeldockSmokeSlow01'), true);
    assert.equal(isYouTubeVideoUrl('https://www.youtube.com/watch?v=reeldockSmoke01'), true);
  });

  it('rejects playlists and random strings', () => {
    assert.equal(isYouTubeWatchUrl('https://www.youtube.com/playlist?list=PLtest'), false);
    assert.equal(isYouTubeWatchUrl('https://example.com/watch?v=reeldockSmoke01'), false);
  });
});

describe('public settings', () => {
  it('never includes the API token', () => {
    const visible = publicSettings({
      serverUrl: 'http://127.0.0.1:8080',
      apiToken: 'secret-token',
      defaultQuality: 'standard',
    });
    assert.equal(visible.serverUrl, 'http://127.0.0.1:8080');
    assert.equal('apiToken' in visible, false);
  });
});

describe('api errors', () => {
  it('turns 401 into actionable token copy', () => {
    assert.match(formatApiError(401), /Invalid extension token/);
  });
});
