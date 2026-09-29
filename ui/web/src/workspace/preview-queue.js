/** @template Snapshot, Result
 * @typedef {Object} PreviewQueueOptions
 * @property {number} [delay]
 * @property {(snapshot: Snapshot) => void} [onStart]
 * @property {(snapshot: Snapshot, result: Result) => void} [onProgress]
 * @property {(snapshot: Snapshot, result: Result) => void} [onResult]
 * @property {(snapshot: Snapshot, error: unknown) => void} [onError]
 * @property {(snapshot: Snapshot) => boolean} [isCurrent]
 */

/** @template Snapshot, Result
 * @param {(snapshot: Snapshot, report: (result: Result) => void, isLatest: () => boolean) => Promise<Result>} render
 * @param {PreviewQueueOptions<Snapshot, Result>} options
 */
export function createLatestPreviewQueue(render, {
  delay = 0,
  onStart = () => {},
  onProgress = () => {},
  onResult = () => {},
  onError = () => {},
  isCurrent = () => true,
}) {
  /** @type {ReturnType<typeof setTimeout> | null} */
  let timer = null;
  /** @type {{snapshot: Snapshot, sequence: number} | null} */
  let pending = null;
  /** @type {{snapshot: Snapshot, sequence: number} | null} */
  let activeRequest = null;
  let requestSequence = 0;
  let inFlight = false;
  let disposed = false;

  async function drain() {
    if (disposed || inFlight || !pending) return;
    const request = pending;
    pending = null;
    inFlight = true;
    activeRequest = request;
    const isLatest = () => (
      request.sequence === requestSequence
      && !disposed
      && isCurrent(request.snapshot)
    );
    try {
      if (!isLatest()) return;
      onStart(request.snapshot);
      const result = await render(
        request.snapshot,
        (progress) => {
          if (isLatest()) onProgress(request.snapshot, progress);
        },
        isLatest,
      );
      if (isLatest()) {
        onResult(request.snapshot, result);
      }
    } catch (error) {
      if (isLatest()) {
        onError(request.snapshot, error);
      }
    } finally {
      activeRequest = null;
      inFlight = false;
      if (pending && !disposed) void drain();
    }
  }

  /** @param {Snapshot} snapshot @param {{immediate?: boolean}} [options] */
  function request(snapshot, { immediate = false } = {}) {
    if (activeRequest?.snapshot === snapshot) return;
    if (pending?.snapshot === snapshot) {
      if (immediate && timer !== null) {
        clearTimeout(timer);
        timer = null;
        void drain();
      }
      return;
    }
    pending = { snapshot, sequence: ++requestSequence };
    if (inFlight) return;
    if (timer !== null) {
      if (!immediate) return;
      clearTimeout(timer);
      timer = null;
    }
    if (immediate) {
      void drain();
    } else {
      timer = setTimeout(() => {
        timer = null;
        void drain();
      }, delay);
    }
  }

  function invalidate() {
    requestSequence += 1;
    pending = null;
    if (timer !== null) clearTimeout(timer);
    timer = null;
  }

  function dispose() {
    invalidate();
    disposed = true;
  }

  return { request, invalidate, dispose };
}
