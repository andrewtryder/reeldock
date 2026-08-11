/** Human labels for job status / phase. */

const STATUS_LABELS = Object.freeze({
  queued: 'Queued',
  running: 'Running',
  downloading: 'Downloading',
  postprocessing: 'Processing',
  converting: 'Converting',
  verifying: 'Verifying',
  scanning: 'Scanning',
  succeeded: 'Complete',
  failed: 'Failed',
  cancelled: 'Cancelled',
});

const PHASE_LABELS = Object.freeze({
  queued: 'Queued',
  resolving_output: 'Preparing',
  running: 'Starting',
  downloading: 'Downloading',
  download_complete: 'Download complete',
  postprocessing: 'Processing',
  converting: 'Converting',
  verifying: 'Verifying',
  scanning: 'Scanning library',
  succeeded: 'Complete',
  failed: 'Failed',
  cancelled: 'Cancelled',
});

export function statusLabel(status) {
  return STATUS_LABELS[status] || status || 'Unknown';
}

export function phaseLabel(phase, status) {
  if (phase && PHASE_LABELS[phase]) return PHASE_LABELS[phase];
  if (status && STATUS_LABELS[status]) return STATUS_LABELS[status];
  return phase || status || 'Working';
}
