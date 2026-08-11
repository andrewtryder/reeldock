/** Map popup/options fields onto the extension queue JSON body. */

export const QUALITY_PRESETS = Object.freeze(['standard', 'high', 'best']);

export function normalizeQuality(quality) {
  const key = String(quality || 'standard').trim().toLowerCase();
  return QUALITY_PRESETS.includes(key) ? key : 'standard';
}

export function shouldOpenReelDockAfterQueue(settings) {
  return settings?.openReelDockAfterQueue === true;
}

export function buildQueuePayload(input = {}) {
  return {
    url: input.url || '',
    destination_folder: input.destinationFolder || '',
    output_title: input.outputTitle || '',
    embed_metadata: input.embedMetadata !== false,
    embed_thumbnail: input.embedThumbnail !== false,
    embed_chapters: input.embedChapters !== false,
    trigger_abs_scan: Boolean(input.triggerAbsScan),
    allow_reimport: Boolean(input.allowReimport),
    quality: normalizeQuality(input.quality),
    sponsorblock_remove: Boolean(input.sponsorblockRemove),
  };
}
