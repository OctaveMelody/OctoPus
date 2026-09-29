/** @typedef {{width: number, height: number, orientation: number}} ImageDimensions */
/** @typedef {{fit: "page" | "width" | "custom", zoom: number, rotation: number, panX: number, panY: number}} ReferenceView */

/** @param {ImageDimensions} image */
export function orientedImageSize(image) {
  return image.orientation >= 5 && image.orientation <= 8
    ? { width: image.height, height: image.width }
    : { width: image.width, height: image.height };
}

/** @param {ImageDimensions} image @param {{width: number, height: number}} viewport @param {ReferenceView} view */
export function referenceFitScale(image, viewport, view) {
  if (viewport.width <= 0 || viewport.height <= 0) return 0;
  const oriented = orientedImageSize(image);
  const quarterTurn = view.rotation % 180 !== 0;
  const width = quarterTurn ? oriented.height : oriented.width;
  const height = quarterTurn ? oriented.width : oriented.height;
  return view.fit === "width"
    ? viewport.width / width
    : Math.min(viewport.width / width, viewport.height / height);
}

/**
 * @param {{width: number, height: number}} viewport
 * @param {number} width
 * @param {number} height
 * @param {number} rotation
 */
export function referenceStageSize(viewport, width, height, rotation) {
  const quarterTurn = rotation % 180 !== 0;
  return {
    width: Math.max(viewport.width, quarterTurn ? height : width),
    height: Math.max(viewport.height, quarterTurn ? width : height),
  };
}

/** @param {{x: number, y: number}} point @param {{width: number, height: number}} viewport @param {ImageDimensions} image @param {ReferenceView} view */
export function viewportPointToSourcePixel(point, viewport, image, view) {
  const scale = referenceFitScale(image, viewport, view) * view.zoom;
  if (!Number.isFinite(scale) || scale <= 0) return null;
  const angle = (view.rotation * Math.PI) / 180;
  const dx = point.x - viewport.width / 2 - view.panX;
  const dy = point.y - viewport.height / 2 - view.panY;
  const centeredX = (Math.cos(angle) * dx + Math.sin(angle) * dy) / scale;
  const centeredY = (-Math.sin(angle) * dx + Math.cos(angle) * dy) / scale;
  const oriented = orientedImageSize(image);
  const x = centeredX + oriented.width / 2;
  const y = centeredY + oriented.height / 2;
  if (x < 0 || x > oriented.width || y < 0 || y > oriented.height) return null;

  const horizontal = x / oriented.width;
  const vertical = y / oriented.height;
  const source = image.orientation === 2
    ? { x: 1 - horizontal, y: vertical }
    : image.orientation === 3
      ? { x: 1 - horizontal, y: 1 - vertical }
      : image.orientation === 4
        ? { x: horizontal, y: 1 - vertical }
        : image.orientation === 5
          ? { x: vertical, y: horizontal }
          : image.orientation === 6
            ? { x: vertical, y: 1 - horizontal }
            : image.orientation === 7
              ? { x: 1 - vertical, y: 1 - horizontal }
              : image.orientation === 8
                ? { x: 1 - vertical, y: horizontal }
                : { x: horizontal, y: vertical };
  return { x: source.x * image.width, y: source.y * image.height };
}
