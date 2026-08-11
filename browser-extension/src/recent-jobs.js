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
    progressPercent: 0,
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
    progressPercent: 0,
    progressLabel: 'Queued',
    errorMessage: '',
    terminalNotificationSent: false,
  };
}

export function droppedJobIds(previousJobs, nextJobs) {
  const keep = new Set((nextJobs || []).map((job) => job.jobId));
  return (previousJobs || []).filter((job) => !keep.has(job.jobId)).map((job) => job.jobId);
}

export function mergeJobFromServer(apiJob, existing = {}) {
  if (!apiJob || typeof apiJob !== 'object') return createJobRecord(existing);
  const jobId = apiJob.id || apiJob.job_id || existing.jobId || '';
  const progress = apiJob.progress_percent ?? apiJob.progress ?? existing.progressPercent ?? 0;
  return createJobRecord({
    ...existing,
    jobId,
    title: apiJob.title || apiJob.output_title || apiJob.source_title || existing.title || '',
    uploader: apiJob.uploader ?? existing.uploader ?? '',
    status: apiJob.status || existing.status || 'queued',
    phase: apiJob.phase || existing.phase || '',
    progressPercent: typeof progress === 'number' ? progress : Number(progress) || 0,
    progressLabel: apiJob.progress_label || existing.progressLabel || '',
    jobUrl: apiJob.job_url || existing.jobUrl || (jobId ? `/jobs/${jobId}` : ''),
    errorMessage: apiJob.error_message || existing.errorMessage || '',
    createdAt: apiJob.created_at || existing.createdAt || '',
  });
}
