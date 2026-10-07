import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { KeyboardEvent, PointerEvent, ReactNode } from "react";

import { AdaptiveToolbar } from "../workspace/AdaptiveToolbar";
import { ActionMenu } from "../workspace/ActionMenu";

import type { messages } from "../workspace/i18n.js";
import { PdfPageCanvas } from "./PdfPageCanvas";
import { orientedImageSize, referenceFitScale, referenceStageSize } from "./reference-view.js";

type Copy = typeof messages.en;
type ReferenceImage = {
  kind: "image";
  id: string;
  name: string;
  mimeType: "image/png" | "image/jpeg";
  byteLength: number;
  width: number;
  height: number;
  orientation: number;
  src: string | null;
};
type ReferencePdfPage = {
  kind: "pdf-page";
  id: string;
  name: string;
  pdfId: string;
  pageNumber: number;
  pageBox: number[];
  pageRotation: number;
  renderScale: 1;
  transform: number[];
  width: number;
  height: number;
  orientation: 1;
  src: string | null;
};
type ReferencePage = ReferenceImage | ReferencePdfPage;
type ReferenceView = {
  fit: "page" | "width" | "custom";
  zoom: number;
  rotation: number;
  panX: number;
  panY: number;
};

type Props = {
  copy: Copy;
  dropActive?: boolean;
  images: ReferencePage[];
  selectedId: string | null;
  views: Record<string, ReferenceView>;
  busy: boolean;
  importing: boolean;
  transcribing: boolean;
  cancelling?: boolean;
  progress?: {completed:number; total:number; stage:string} | null;
  onCancel?(): void;
  reviewRegion?: {id:string; boxes:number[][]; serial:number} | null;
  showHint?: boolean;
  onDismissHint?(): void;
  transcriptionControl: ReactNode;
  visible: boolean;
  renderErrorLabel: string;
  controls?: ReactNode;
  hidden?: boolean;
  onSelect(id: string): void;
  onViewChange(id: string, patch: Partial<ReferenceView>): void;
};

export function ReferencePanel({
  copy,
  dropActive = false,
  images,
  selectedId,
  views,
  busy,
  transcribing, cancelling = false, progress = null, onCancel, reviewRegion = null,
  showHint = false, onDismissHint,
  transcriptionControl,
  visible,
  renderErrorLabel,
  controls,
  hidden,
  onSelect,
  onViewChange,
}: Props) {
  const viewportRef = useRef<HTMLDivElement>(null);
  const pendingReviewCenter = useRef<{
    id: string; serial: number; zoom: number; panX: number; panY: number;
  } | null>(null);
  const hasPdfPages = useRef(false);
  const containsPdfPages = images.some((page) => page.kind === "pdf-page");
  hasPdfPages.current = containsPdfPages;
  const drag = useRef<{ pointerId: number; x: number; y: number; panX: number; panY: number } | null>(null);
  const [viewport, setViewport] = useState({ width: 0, height: 0 });
  const [failedImageId, setFailedImageId] = useState<string | null>(null);
  const [failedPdfMessage, setFailedPdfMessage] = useState<string | null>(null);
  const hasImages = images.length > 0;
  const transcriptionStatus = cancelling
    ? copy.cancellingTranscription
    : progress?.stage === "compiling"
      ? copy.compilingTranscription
      : copy.transcribing;
  const image = images.find((item) => item.id === selectedId) ?? null;
  const view = image
    ? views[image.id] ?? { fit: "width", zoom: 1, rotation: 0, panX: 0, panY: 0 }
    : null;

  useEffect(() => {
    const element = viewportRef.current;
    if (!element) return;
    const updateSize = () => {
      setViewport({ width: element.clientWidth, height: element.clientHeight });
    };
    updateSize();
    const observer = new ResizeObserver(updateSize);
    observer.observe(element);
    return () => observer.disconnect();
  }, [hasImages]);

  useEffect(() => setFailedImageId(null), [image?.id, image?.src]);
  useEffect(() => setFailedPdfMessage(null), [image?.id, image?.src]);
  useEffect(() => () => {
    if (!hasPdfPages.current) return;
    void import("./pdf-runtime")
      .then(({ closeAllPdfDocuments }) => closeAllPdfDocuments())
      .catch(() => {});
  }, []);
  useEffect(() => {
    if (visible || !hasPdfPages.current) return;
    void import("./pdf-runtime")
      .then(({ closeAllPdfDocuments }) => closeAllPdfDocuments())
      .catch(() => {});
  }, [containsPdfPages, visible]);

  useLayoutEffect(() => {
    if (!image || !reviewRegion || reviewRegion.id !== image.id || !reviewRegion.boxes.length) return;
    const element = viewportRef.current;
    if (!element || element.clientWidth <= 0 || element.clientHeight <= 0) return;
    const size = orientedImageSize(image);
    const boxes = reviewRegion.boxes;
    const left = Math.min(...boxes.map(box => box[0]));
    const top = Math.min(...boxes.map(box => box[1]));
    const right = Math.max(...boxes.map(box => box[2]));
    const bottom = Math.max(...boxes.map(box => box[3]));
    const baseScale = Math.min(element.clientWidth / size.width, element.clientHeight / size.height);
    const scale = Math.min(element.clientWidth / (Math.max(0.08, right-left) * size.width * 1.4),
      element.clientHeight / (Math.max(0.08, bottom-top) * size.height * 1.4));
    const zoom = Math.max(1, Math.min(4, scale / baseScale));
    const width = size.width * baseScale * zoom;
    const height = size.height * baseScale * zoom;
    const panX = -(left + right - 1) / 2 * width;
    const panY = -(top + bottom - 1) / 2 * height;
    pendingReviewCenter.current = { id: image.id, serial: reviewRegion.serial, zoom, panX, panY };
    onViewChange(image.id, {fit: "page", zoom, rotation: 0, panX, panY});
  }, [reviewRegion?.serial, image?.id]);

  function onPointerDown(event: PointerEvent<HTMLDivElement>) {
    if (
      busy
      || !image
      || event.pointerType === "touch"
      || event.button !== 0
      || !event.isPrimary
    ) return;
    const bounds = event.currentTarget.getBoundingClientRect();
    if (
      event.clientX >= bounds.left + event.currentTarget.clientWidth
      || event.clientY >= bounds.top + event.currentTarget.clientHeight
    ) return;
    drag.current = {
      pointerId: event.pointerId,
      x: event.clientX,
      y: event.clientY,
      panX: view?.panX ?? 0,
      panY: view?.panY ?? 0,
    };
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function onPointerMove(event: PointerEvent<HTMLDivElement>) {
    const start = drag.current;
    if (busy || !start || start.pointerId !== event.pointerId || !image) return;
    onViewChange(image.id, {
      panX: start.panX + event.clientX - start.x,
      panY: start.panY + event.clientY - start.y,
    });
  }

  function onPointerUp(event: PointerEvent<HTMLDivElement>) {
    if (drag.current?.pointerId !== event.pointerId) return;
    drag.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  }

  function onViewportKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (busy || !image || !view || !event.key.startsWith("Arrow")) return;
    event.preventDefault();
    const amount = event.shiftKey ? 100 : 40;
    onViewChange(image.id, {
      panX: view.panX + (event.key === "ArrowLeft" ? amount : event.key === "ArrowRight" ? -amount : 0),
      panY: view.panY + (event.key === "ArrowUp" ? amount : event.key === "ArrowDown" ? -amount : 0),
    });
  }

  const imageSize = image ? orientedImageSize(image) : null;
  const sourcePages = image
    ? images.filter((page) => image.kind === "pdf-page"
      ? page.kind === "pdf-page" && page.pdfId === image.pdfId
      : page.id === image.id)
    : [];
  const sourcePageIndex = sourcePages.findIndex((page) => page.id === image?.id);
  const fitScale = image && view ? referenceFitScale(image, viewport, view) : 0;
  const zoomScale = fitScale * (view?.zoom ?? 1);
  const scaledWidth = (imageSize?.width ?? 0) * zoomScale;
  const scaledHeight = (imageSize?.height ?? 0) * zoomScale;
  const stageSize = view
    ? referenceStageSize(viewport, scaledWidth, scaledHeight, view.rotation)
    : viewport;

  useLayoutEffect(() => {
    const pending = pendingReviewCenter.current;
    const element = viewportRef.current;
    if (!pending || !element || !view || pending.id !== image?.id
      || pending.serial !== reviewRegion?.serial || view.fit !== "page" || view.rotation !== 0
      || view.zoom !== pending.zoom || view.panX !== pending.panX || view.panY !== pending.panY) return;
    // Measure after the zoomed stage commits; scrolling earlier clamps to the previous stage.
    const boxes = [...element.querySelectorAll(".reference-review-overlay span")]
      .map(box => box.getBoundingClientRect());
    if (!boxes.length) return;
    const bounds = element.getBoundingClientRect();
    const centerX = (Math.min(...boxes.map(box => box.left))
      + Math.max(...boxes.map(box => box.right))) / 2;
    const centerY = (Math.min(...boxes.map(box => box.top))
      + Math.max(...boxes.map(box => box.bottom))) / 2;
    element.scrollLeft += centerX - bounds.left - element.clientLeft - element.clientWidth / 2;
    element.scrollTop += centerY - bounds.top - element.clientTop - element.clientHeight / 2;
    pendingReviewCenter.current = null;
  }, [image?.id, reviewRegion?.serial, view?.fit, view?.rotation, view?.zoom, view?.panX,
    view?.panY, stageSize.width, stageSize.height]);

  return (
    <section hidden={hidden} aria-label={copy.reference} className={`panel reference-panel${dropActive ? " reference-drop-active" : ""}`}
      onDragOver={event => { event.preventDefault(); }}
      onDrop={event => { event.preventDefault(); }}>
      {dropActive && <div className="reference-drop-hint" role="status">{copy.dropReferenceHint}</div>}
      <div className="panel-heading">
        <div className="reference-heading-title">
          <h2>{copy.reference}</h2>
          {image && <span className="reference-current-name" title={image.name}>{image.name}</span>}
        </div>
        <AdaptiveToolbar label={copy.referenceTools} className="preview-tools reference-preview-tools"
          expanded={<>
          {image && sourcePages.length > 1 && (
            <>
              <button
                aria-label={copy.previousReferencePage}
                disabled={busy || sourcePageIndex <= 0}
                onClick={() => onSelect(sourcePages[sourcePageIndex - 1].id)}
                type="button"
              >‹</button>
              <span>{copy.referenceImageCount(sourcePageIndex + 1, sourcePages.length)}</span>
              <button
                aria-label={copy.nextReferencePage}
                disabled={busy || sourcePageIndex >= sourcePages.length - 1}
                onClick={() => onSelect(sourcePages[sourcePageIndex + 1].id)}
                type="button"
              >›</button>
            </>
          )}
          <button
            aria-label={copy.zoomOut}
            disabled={busy || !image || !view || view.zoom <= 0.5}
            onClick={() => image && view && onViewChange(image.id, {
              zoom: Math.max(0.5, view.zoom - 0.25),
            })}
            type="button"
          >−</button>
          <span>{copy.zoomPercent(Math.round((view?.zoom ?? 1) * 100))}</span>
          <button
            aria-label={copy.zoomIn}
            disabled={busy || !image || !view || view.zoom >= 4}
            onClick={() => image && view && onViewChange(image.id, {
              zoom: Math.min(4, view.zoom + 0.25),
            })}
            type="button"
          >+</button>
          <button disabled={busy || !image} onClick={() => image && onViewChange(image.id, {
            fit: "page", zoom: 1, panX: 0, panY: 0,
          })} type="button">{copy.fitPage}</button>
          <button disabled={busy || !image} onClick={() => image && onViewChange(image.id, {
            fit: "width", zoom: 1, panX: 0, panY: 0,
          })} type="button">{copy.fitWidth}</button>
          <div className="reference-transcription-tools">
            <button
              aria-label={copy.rotateImage}
              disabled={busy || !image}
              onClick={() => image && view && onViewChange(image.id, {
                rotation: (view.rotation + 90) % 360,
              })}
              title={copy.rotateImage}
              type="button"
            >↻ 90°</button>
          </div>
        </>} compact={<>
          {image && sourcePages.length > 1 && <span>{copy.referenceImageCount(sourcePageIndex + 1, sourcePages.length)}</span>}
          <button aria-label={copy.zoomOut} disabled={busy || !image || !view || view.zoom <= 0.5}
            onClick={() => image && view && onViewChange(image.id, {zoom: Math.max(0.5, view.zoom - 0.25)})}
            type="button">−</button>
          <span>{copy.zoomPercent(Math.round((view?.zoom ?? 1) * 100))}</span>
          <button aria-label={copy.zoomIn} disabled={busy || !image || !view || view.zoom >= 4}
            onClick={() => image && view && onViewChange(image.id, {zoom: Math.min(4, view.zoom + 0.25)})}
            type="button">+</button>
          <ActionMenu label={copy.viewMenu} actions={[
            {label: copy.fitPage, disabled: busy || !image,
              run: () => { if (image) onViewChange(image.id, {fit: "page", zoom: 1, panX: 0, panY: 0}); }},
            {label: copy.fitWidth, disabled: busy || !image,
              run: () => { if (image) onViewChange(image.id, {fit: "width", zoom: 1, panX: 0, panY: 0}); }},
            {label: copy.zoomOut, disabled: busy || !image || !view || view.zoom <= 0.5,
              run: () => { if (image && view) onViewChange(image.id, {zoom: Math.max(0.5, view.zoom - 0.25)}); }},
            {label: copy.zoomIn, disabled: busy || !image || !view || view.zoom >= 4,
              run: () => { if (image && view) onViewChange(image.id, {zoom: Math.min(4, view.zoom + 0.25)}); }},
            {label: copy.rotateImage, disabled: busy || !image || !view,
              run: () => { if (image && view) onViewChange(image.id, {rotation: (view.rotation + 90) % 360}); }},
            ...(sourcePages.length > 1 ? [
              {label: copy.prevPageMenu, disabled: busy || sourcePageIndex <= 0,
                run: () => onSelect(sourcePages[sourcePageIndex - 1].id)},
              {label: copy.nextPageMenu, disabled: busy || sourcePageIndex >= sourcePages.length - 1,
                run: () => onSelect(sourcePages[sourcePageIndex + 1].id)},
            ] : []),
          ]}/>
        </>}/>
        <div className="reference-heading-transcribe">{transcriptionControl}</div>
        {controls}
      </div>
      {showHint && <aside className="reference-onboarding"><p>{copy.referenceHint}</p>
        <button type="button" aria-label={copy.dismissHint} onClick={onDismissHint}>×</button></aside>}
      {transcribing && (
        <div aria-busy="true" className="reference-transcription-progress" role="status">
          <span className="reference-transcription-status">{transcriptionStatus}</span>
          <div aria-label={copy.transcribing} aria-valuetext={transcriptionStatus}
            className="reference-transcription-progressbar" role="progressbar">
            <span className="reference-transcription-progressbar-indicator" />
          </div>
          <button type="button" disabled={cancelling} onClick={onCancel}>{copy.cancelTranscription}</button>
        </div>
      )}
      {images.length === 0 ? (
        <div className="reference-empty">
          <p>{copy.referenceEmpty}</p>
          <span>{copy.importLater}</span>
          <span>{copy.dropReferenceHint}</span>
        </div>
      ) : (
        <>
          <div
            aria-label={image ? copy.reference : copy.noReferenceSelected}
            className="reference-image-viewport"
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
            onPointerCancel={onPointerUp}
            onKeyDown={onViewportKeyDown}
            ref={viewportRef}
            role="region"
            tabIndex={0}
          >
            {image ? (
              <div
                className="reference-image-stage"
                style={{ height: `${stageSize.height}px`, width: `${stageSize.width}px` }}
              >
                {reviewRegion?.id === image.id && reviewRegion.boxes.length > 0 && <div
                  className="reference-review-overlay" aria-hidden="true" style={{
                    width: `${scaledWidth}px`, height: `${scaledHeight}px`,
                    transform: `translate(-50%, -50%) translate(${view?.panX ?? 0}px, ${view?.panY ?? 0}px) rotate(${view?.rotation ?? 0}deg)`,
                  }}>{reviewRegion.boxes.map((box, index) => <span key={index} style={{
                    left: `${box[0]*100}%`, top: `${box[1]*100}%`,
                    width: `${(box[2]-box[0])*100}%`, height: `${(box[3]-box[1])*100}%`,
                  }}/>)}</div>}
                {image.kind === "pdf-page" && image.src ? (
                  <>
                    <PdfPageCanvas
                      active={visible}
                      errorLabel={renderErrorLabel}
                      label={copy.referenceImageAlt(copy.referencePdfPage(image.name, image.pageNumber))}
                      onRenderError={setFailedPdfMessage}
                      pageNumber={image.pageNumber}
                      scale={zoomScale}
                      source={image.src}
                      style={{
                        height: `${scaledHeight}px`,
                        transform: `translate(-50%, -50%) translate(${view?.panX ?? 0}px, ${view?.panY ?? 0}px) rotate(${view?.rotation ?? 0}deg)`,
                        width: `${scaledWidth}px`,
                      }}
                    />
                    {failedPdfMessage && <p role="status">{renderErrorLabel} {failedPdfMessage}</p>}
                  </>
                ) : image.kind === "image" && image.src && failedImageId !== image.id ? (
                  <img
                    alt={copy.referenceImageAlt(image.name)}
                    draggable={false}
                    onError={() => setFailedImageId(image.id)}
                    src={image.src}
                    style={{
                      height: `${scaledHeight}px`,
                      transform: `translate(-50%, -50%) translate(${view?.panX ?? 0}px, ${view?.panY ?? 0}px) rotate(${view?.rotation ?? 0}deg)`,
                      width: `${scaledWidth}px`,
                    }}
                  />
                ) : (
                  <p>{copy.referenceImageMissing}</p>
                )}
              </div>
            ) : (
              <p>{copy.noReferenceSelected}</p>
            )}
          </div>
        </>
      )}
    </section>
  );
}
