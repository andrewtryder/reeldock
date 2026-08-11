/** Map popup/options fields onto the extension queue JSON body. */

import { LIBRARY_ROOT_VALUE, SERVER_DEFAULT_VALUE } from './destinations.js';

export const QUALITY_PRESETS = Object.freeze(['standard', 'high', 'best']);

export function normalizeQuality(quality) {
  const key = String(quality || 'standard').trim().toLowerCase();
  return QUALITY_PRESETS.includes(key) ? key : 'standard';
}

export function shouldOpenReelDockAfterQueue(settings) {
  return settings?.openReelDockAfterQueue === true;
}

/** Map UI/storage sentinel onto the wire destination_folder value, or undefined to omit. */
export function destinationFolderForQueue(destinationFolder) {
  if (destinationFolder == null || destinationFolder === SERVER_DEFAULT_VALUE) {
    return undefined;
  }
  if (destinationFolder === LIBRARY_ROOT_VALUE) {
    return '';
  }
  return destinationFolder;
}

export function buildQueuePayload(input = {}) {
  const body = {
    url: input.url || '',
    output_title: input.outputTitle || '',
    embed_metadata: input.embedMetadata !== false,
    embed_thumbnail: input.embedThumbnail !== false,
    embed_chapters: input.embedChapters !== false,
    trigger_abs_scan: Boolean(input.triggerAbsScan),
    allow_reimport: Boolean(input.allowReimport),
    quality: normalizeQuality(input.quality),
    sponsorblock_remove: Boolean(input.sponsorblockRemove),
  };
  if (!('destinationFolder' in input)) {
    return body;
  }
  const destination = destinationFolderForQueue(input.destinationFolder);
  if (destination !== undefined) {
    body.destination_folder = destination;
  }
  return body;
}
