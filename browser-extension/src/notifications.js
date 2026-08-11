/** Notification ids and copy. Dedupes terminal alerts via an in-memory claim. */

const claimedTerminalNotifications = new Set();

export function claimTerminalNotification(jobId) {
  if (!jobId) return false;
  if (claimedTerminalNotifications.has(jobId)) return false;
  claimedTerminalNotifications.add(jobId);
  return true;
}

export function releaseTerminalNotificationClaim(jobId) {
  if (!jobId) return;
  claimedTerminalNotifications.delete(jobId);
}

export function resetTerminalNotificationClaims() {
  claimedTerminalNotifications.clear();
}

export async function notifyTerminalOnce(job, createNotification) {
  const spec = terminalNotificationSpec(job);
  if (!spec) return false;
  if (!claimTerminalNotification(job.jobId)) return false;
  await createNotification(spec);
  return true;
}

export function queuedNotificationId(jobId) {
  return `reeldock-queue-${jobId}`;
}

export function doneNotificationId(jobId) {
  return `reeldock-done-${jobId}`;
}

export function failNotificationId(jobId) {
  return `reeldock-fail-${jobId}`;
}

export function parseNotificationJobId(notificationId) {
  const match = String(notificationId || '').match(/^reeldock-(?:queue|done|fail)-(.+)$/);
  return match ? match[1] : '';
}

/**
 * Context-menu queue gets one OS notification. Popup queue does not.
 * @param {{ jobId: string, title?: string }} job
 * @param {{ source?: string }} options
 */
export function queuedNotificationSpec(job, options = {}) {
  if (options.source !== 'contextMenu') return null;
  const title = job?.title || job?.jobId || 'Audiobook';
  return {
    id: queuedNotificationId(job.jobId),
    title: 'Audiobook queued',
    message: title,
  };
}

export function shouldSendTerminalNotification(job) {
  if (!job || job.terminalNotificationSent) return false;
  return job.status === 'succeeded' || job.status === 'failed' || job.status === 'cancelled';
}

export function terminalNotificationSpec(job) {
  if (!shouldSendTerminalNotification(job)) return null;
  const name = job.title || job.jobId || 'Audiobook';
  if (job.status === 'succeeded') {
    return {
      id: doneNotificationId(job.jobId),
      title: 'Audiobook ready',
      message: name,
    };
  }
  if (job.status === 'failed') {
    return {
      id: failNotificationId(job.jobId),
      title: 'Audiobook failed',
      message: job.errorMessage || name,
    };
  }
  return {
    id: failNotificationId(job.jobId),
    title: 'Audiobook cancelled',
    message: name,
  };
}
