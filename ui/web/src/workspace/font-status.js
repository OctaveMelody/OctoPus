/** @typedef {{family: string, fallback: string, available: boolean}} FontStatus */

/** @param {Record<string, FontStatus> | undefined} fonts */
export function missingPreferredFonts(fonts) {
  return Object.entries(fonts ?? {})
    .filter(([, font]) => font.available === false)
    .sort(([left], [right]) => left.localeCompare(right));
}

/** @param {{pageCount: number, pages: Map<number, {font_roles?: string[]}>} | null} cache */
export function usedFontRoles(cache) {
  if (!cache || cache.pages.size !== cache.pageCount) return null;
  return [...new Set([...cache.pages.values()].flatMap(page => page.font_roles ?? []))].sort();
}

/** @param {string} policy @param {string} platform @param {[string, FontStatus][]} missing */
export function fontNoticeKey(policy, platform, missing) {
  if (missing.length === 0) return "";
  return JSON.stringify([
    policy,
    platform,
    missing.map(([role, font]) => [role, font.family]),
  ]);
}
