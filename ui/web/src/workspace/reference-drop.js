/** @param {string[]} paths @returns {"empty" | "multiple" | "unsupported" | "supported"} */
export function referenceDropKind(paths) {
  if (paths.length === 0) return "empty";
  if (paths.length !== 1) return "multiple";
  return /\.(png|jpe?g|pdf)$/i.test(paths[0]) ? "supported" : "unsupported";
}

/** @param {{x: number, y: number} | null} position
 * @param {{left: number, top: number, right: number, bottom: number, width: number, height: number} | null} bounds
 * @param {number} ratio */
export function referenceDropInside(position, bounds, ratio = 1) {
  if (!position || !bounds || bounds.width <= 0 || bounds.height <= 0
    || !Number.isFinite(position.x) || !Number.isFinite(position.y)
    || !Number.isFinite(ratio) || ratio <= 0) return false;
  const x = position.x / ratio;
  const y = position.y / ratio;
  return x >= bounds.left && x < bounds.right && y >= bounds.top && y < bounds.bottom;
}
