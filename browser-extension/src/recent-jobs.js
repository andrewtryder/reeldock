/** Recent-job ledger: upsert, cap, display, and retry reset. No token. */

export const RECENT_JOBS_KEY = 'recentJobs';
export const MAX_RECENT_JOBS = 10;
export const DISPLAY_RECENT_JOBS = 5;

export const TERMINAL_STATUSES = Object.freeze(['succeeded', 'failed', 'cancelled']);

export function isTerminalStatus(status) {
  return TERMINAL_STATUSES.includes(status);
}

export function createJobRecord(partial = {}) {
  return {
    jobId: '',
    title: '',
    uploader: '',
    status: 'queued',
    phase: '',
    progressPercent: null,
    progressLabel: '',
    jobUrl: '',
    serverOrigin: '',
    createdAt: '',
    errorMessage: '',
    terminalNotificationSent: false,
    ...partial,
  };
}

export function upsertRecentJob(jobs, record) {
  const incoming = createJobRecord(record);
  if (!incoming.jobId) return [...jobs];
  const next = [incoming, ...jobs.filter((job) => job.jobId !== incoming.jobId)];
  return next.slice(0, MAX_RECENT_JOBS);
}

export function displayRecentJobs(jobs) {
  return (jobs || []).slice(0, DISPLAY_RECENT_JOBS);
}

export function applyJobPatch(jobs, jobId, patch) {
  return (jobs || []).map((job) => (job.jobId === jobId ? { ...job, ...patch } : job));
}

export function resetJobForRetry(job) {
  return {
    ...job,
    status: 'queued',
    phase: 'queued',
    progressPercent: null,
    progressLabel: 'Queued',
    errorMessage: '',
    terminalNotificationSent: false,
  };
}

export function droppedJobIds(previousJobs, nextJobs) {
  const keep = new Set((nextJobs || []).map((job) => job.jobId));
  return (previousJobs || []).filter((job) => !keep.has(job.jobId)).map((job) => job.jobId);
}

function coerceProgressPercent(value) {
  if (value == null) return null;
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export function jobMatchesServerOrigin(job, origin) {
  const want = String(origin || '').replace(/\/$/, '');
  const have = String(job?.serverOrigin || '').replace(/\/$/, '');
  return !have || have === want;
}

export function mergeJobFromServer(apiJob, existing = {}) {
  if (!apiJob || typeof apiJob !== 'object') return createJobRecord(existing);
  const jobId = apiJob.id || apiJob.job_id || existing.jobId || '';
  let progressPercent;
  if (Object.prototype.hasOwnProperty.call(apiJob, 'progress_percent')) {
    progressPercent = coerceProgressPercent(apiJob.progress_percent);
  } else if (Object.prototype.hasOwnProperty.call(apiJob, 'progress')) {
    progressPercent = coerceProgressPercent(apiJob.progress);
  } else {
    progressPercent = existing.progressPercent ?? null;
  }
  return createJobRecord({
    ...existing,
    jobId,
    title: apiJob.title || apiJob.output_title || apiJob.source_title || existing.title || '',
    uploader: apiJob.uploader ?? existing.uploader ?? '',
    status: apiJob.status || existing.status || 'queued',
    phase: apiJob.phase || existing.phase || '',
    progressPercent,
    progressLabel: apiJob.progress_label || existing.progressLabel || '',
    jobUrl: apiJob.job_url || existing.jobUrl || (jobId ? `/jobs/${jobId}` : ''),
    errorMessage: apiJob.error_message || existing.errorMessage || '',
    createdAt: apiJob.created_at || existing.createdAt || '',
    terminalNotificationSent: existing.terminalNotificationSent === true,
  });
}
