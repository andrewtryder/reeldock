import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import {
  DISPLAY_RECENT_JOBS,
  MAX_RECENT_JOBS,
  applyJobPatch,
  createJobRecord,
  displayRecentJobs,
  droppedJobIds,
  isTerminalStatus,
  jobMatchesServerOrigin,
  mergeJobFromServer,
  resetJobForRetry,
  upsertRecentJob,
} from '../src/recent-jobs.js';

function job(id, extra = {}) {
  return createJobRecord({ jobId: id, title: id, ...extra });
}

describe('recent job ledger', () => {
  it('upserts by jobId and keeps the newest first', () => {
    let jobs = [];
    jobs = upsertRecentJob(jobs, job('a', { status: 'queued' }));
    jobs = upsertRecentJob(jobs, job('b', { status: 'queued' }));
    jobs = upsertRecentJob(jobs, job('a', { status: 'running', title: 'Updated' }));
    assert.equal(jobs[0].jobId, 'a');
    assert.equal(jobs[0].title, 'Updated');
    assert.equal(jobs[0].status, 'running');
    assert.equal(jobs.length, 2);
  });

  it('caps stored jobs at 10', () => {
    let jobs = [];
    for (let i = 0; i < 12; i += 1) {
      jobs = upsertRecentJob(jobs, job(`job-${i}`));
    }
    assert.equal(jobs.length, MAX_RECENT_JOBS);
    assert.equal(jobs[0].jobId, 'job-11');
    assert.equal(jobs.at(-1).jobId, 'job-2');
  });

  it('displays only the first 5', () => {
    const jobs = Array.from({ length: 8 }, (_, i) => job(`job-${i}`));
    assert.equal(displayRecentJobs(jobs).length, DISPLAY_RECENT_JOBS);
  });

  it('detects terminal statuses', () => {
    assert.equal(isTerminalStatus('succeeded'), true);
    assert.equal(isTerminalStatus('failed'), true);
    assert.equal(isTerminalStatus('cancelled'), true);
    assert.equal(isTerminalStatus('running'), false);
    assert.equal(isTerminalStatus('queued'), false);
  });

  it('resets retry state including terminalNotificationSent', () => {
    const reset = resetJobForRetry(
      job('x', {
        status: 'failed',
        phase: 'failed',
        errorMessage: 'boom',
        terminalNotificationSent: true,
        progressPercent: 40,
      }),
    );
    assert.equal(reset.status, 'queued');
    assert.equal(reset.phase, 'queued');
    assert.equal(reset.errorMessage, '');
    assert.equal(reset.terminalNotificationSent, false);
    assert.equal(reset.progressPercent, null);
  });

  it('honors explicit null progress_percent after convert 100', () => {
    const afterConvert = mergeJobFromServer(
      {
        id: 'abc',
        status: 'converting',
        progress_percent: 100,
        progress_label: 'Converting',
      },
      job('abc', { progressPercent: 40 }),
    );
    assert.equal(afterConvert.progressPercent, 100);
    const afterVerify = mergeJobFromServer(
      {
        id: 'abc',
        status: 'verifying',
        progress_percent: null,
        progress_label: 'Verifying',
      },
      afterConvert,
    );
    assert.equal(afterVerify.progressPercent, null);
    assert.equal(afterVerify.progressLabel, 'Verifying');
  });

  it('never copies terminalNotificationSent from the server payload', () => {
    const merged = mergeJobFromServer(
      { id: 'abc', status: 'succeeded', terminalNotificationSent: false },
      job('abc', { terminalNotificationSent: true }),
    );
    assert.equal(merged.terminalNotificationSent, true);
  });

  it('scopes jobs to the current server origin', () => {
    const local = job('a', { serverOrigin: 'http://127.0.0.1:8080' });
    const other = job('b', { serverOrigin: 'https://other.example' });
    const legacy = job('c', { serverOrigin: '' });
    assert.equal(jobMatchesServerOrigin(local, 'http://127.0.0.1:8080'), true);
    assert.equal(jobMatchesServerOrigin(other, 'http://127.0.0.1:8080'), false);
    assert.equal(jobMatchesServerOrigin(legacy, 'http://127.0.0.1:8080'), true);
  });

  it('merges slim and web-UI job payloads', () => {
    const merged = mergeJobFromServer(
      {
        id: 'abc',
        output_title: 'Book',
        uploader: 'Chan',
        status: 'downloading',
        progress_percent: 12,
        progress_label: 'Downloading',
        job_url: '/jobs/abc',
      },
      job('abc', { serverOrigin: 'http://127.0.0.1:8080' }),
    );
    assert.equal(merged.title, 'Book');
    assert.equal(merged.progressPercent, 12);
    assert.equal(merged.serverOrigin, 'http://127.0.0.1:8080');
  });

  it('reports jobs dropped by the 10-cap', () => {
    const previous = [job('keep'), job('drop')];
    const next = [job('keep')];
    assert.deepEqual(droppedJobIds(previous, next), ['drop']);
  });

  it('patches a single job', () => {
    const jobs = applyJobPatch([job('a'), job('b')], 'b', { status: 'cancelled' });
    assert.equal(jobs[1].status, 'cancelled');
    assert.equal(jobs[0].status, 'queued');
  });
});
