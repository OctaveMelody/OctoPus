/** @param {unknown} paths @returns {string[]} */
export function normalizeRecentFiles(paths) {
  if (!Array.isArray(paths)) return [];
  const unique = new Set();
  return paths.filter(path => {
    if (typeof path !== "string" || !path.trim() || path.includes("\0") || unique.has(path)) return false;
    unique.add(path);
    return true;
  }).slice(0, 10);
}
/** @param {string[]} paths @param {string} path */
export function rememberRecentFile(paths, path) {
  return normalizeRecentFiles([path, ...paths]);
}
