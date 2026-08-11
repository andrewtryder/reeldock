import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import {
  doneNotificationId,
  failNotificationId,
  notifyTerminalOnce,
  parseNotificationJobId,
  queuedNotificationId,
  queuedNotificationSpec,
  resetTerminalNotificationClaims,
  shouldSendTerminalNotification,
  terminalNotificationSpec,
} from '../src/notifications.js';

describe('notifications', () => {
  it('uses stable ids', () => {
    assert.equal(queuedNotificationId('abc'), 'reeldock-queue-abc');
    assert.equal(doneNotificationId('abc'), 'reeldock-done-abc');
    assert.equal(failNotificationId('abc'), 'reeldock-fail-abc');
    assert.equal(parseNotificationJobId('reeldock-done-abc'), 'abc');
  });

  it('notifies on context-menu queue but not popup queue', () => {
    const job = { jobId: 'j1', title: 'Sermon One' };
    const context = queuedNotificationSpec(job, { source: 'contextMenu' });
    assert.ok(context);
    assert.equal(context.id, 'reeldock-queue-j1');
    assert.equal(context.title, 'Audiobook queued');
    assert.equal(context.message, 'Sermon One');
    assert.equal(queuedNotificationSpec(job, { source: 'popup' }), null);
    assert.equal(queuedNotificationSpec(job, {}), null);
  });

  it('sends exactly one terminal notification until retry reset', () => {
    const job = { jobId: 'j1', title: 'Sermon One', status: 'succeeded', terminalNotificationSent: false };
    const spec = terminalNotificationSpec(job);
    assert.equal(spec.id, 'reeldock-done-j1');
    assert.equal(spec.title, 'Audiobook ready');
    assert.equal(shouldSendTerminalNotification({ ...job, terminalNotificationSent: true }), false);
    assert.equal(terminalNotificationSpec({ ...job, terminalNotificationSent: true }), null);
  });

  it('uses failure copy and id for failed jobs', () => {
    const spec = terminalNotificationSpec({
      jobId: 'j2',
      title: 'Bad',
      status: 'failed',
      errorMessage: 'yt-dlp failed',
      terminalNotificationSent: false,
    });
    assert.equal(spec.id, 'reeldock-fail-j2');
    assert.equal(spec.title, 'Audiobook failed');
    assert.equal(spec.message, 'yt-dlp failed');
  });

  it('creates only one notification for two overlapping terminal updates', async () => {
    resetTerminalNotificationClaims();
    const created = [];
    const job = {
      jobId: 'overlap-1',
      title: 'Sermon',
      status: 'succeeded',
      terminalNotificationSent: false,
    };
    const create = async (spec) => {
      created.push(spec.id);
    };
    await Promise.all([notifyTerminalOnce(job, create), notifyTerminalOnce(job, create)]);
    assert.deepEqual(created, ['reeldock-done-overlap-1']);
  });
});
