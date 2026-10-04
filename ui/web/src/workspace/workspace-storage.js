/** @returns {Storage | null} */
export function getStorage() {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}
