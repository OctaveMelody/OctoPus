import { AdaptiveToolbar } from "./AdaptiveToolbar";
import { ActionMenu } from "./ActionMenu";
import type { useScorePreview } from "./useScorePreview";
import type { Status, WorkspaceCopy } from "./types";

function statusText(status: Status, copy: WorkspaceCopy): string {
  switch (status.kind) {
    case "ready": return copy.ready;
    case "rendering": return copy.rendering;
    case "changed": return copy.changed;
    case "preferences": return copy.preferenceWarning;
    case "saved": return copy.saved;
    case "notice": return copy.encodingRepaired;
    case "rendered": return copy.rendered(status.pages);
    case "transcribing": return copy.transcribing;
    case "transcribed": return copy.transcribed(status.issues);
    case "error": return status.message;
  }
}

export function ScorePreview({ preview, copy, documentOpen, status }: {
  preview: ReturnType<typeof useScorePreview>;
  copy: WorkspaceCopy;
  documentOpen: boolean;
  status: Status;
}) {
  const { currentPageCache, currentPage, selectedPage, previewZoom, setPreviewZoom, setPreviewFit,
    displayedPreview, previewScale, previewIsCurrent, previewUrl, previewCanvasRef, previewImageRef,
    cursorMarkerRef,
    highlightPage, cursorAnchor, cursorRowBounds, diagnostics, jumpToDiagnostic,
    selectPage, renderSelectedPage, selectPreviewAnchor, previewImageSettled } = preview;
  return (
    <section aria-label={copy.preview} className="panel preview-panel" key="preview">
      <div className="panel-heading">
        <h2>{copy.preview}</h2>
        <AdaptiveToolbar label={copy.previewTools} className="preview-tools"
          expanded={<>
          {currentPageCache && (
            <>
              <button
                aria-label={copy.previousPage}
                disabled={selectedPage <= 0}
                onClick={() => selectPage(selectedPage - 1)}
                type="button"
              >‹</button>
              <span>{copy.page} {selectedPage + 1} / {currentPageCache.pageCount}</span>
              <button
                aria-label={copy.nextPage}
                disabled={selectedPage + 1 >= currentPageCache.pageCount}
                onClick={() => selectPage(selectedPage + 1)}
                type="button"
              >›</button>
            </>
          )}
          <button
            aria-label={copy.zoomOut}
            disabled={previewZoom <= 0.5}
            onClick={() => setPreviewZoom((zoom) => Math.max(0.5, zoom - 0.25))}
            type="button"
          >−</button>
          <span>{copy.zoomPercent(Math.round(previewZoom * 100))}</span>
          <button
            aria-label={copy.zoomIn}
            disabled={previewZoom >= 4}
            onClick={() => setPreviewZoom((zoom) => Math.min(4, zoom + 0.25))}
            type="button"
          >+</button>
          <button
            disabled={!displayedPreview}
            onClick={() => {
              setPreviewFit("page");
              setPreviewZoom(1);
            }}
            type="button"
          >{copy.fitPage}</button>
          <button
            onClick={() => {
              setPreviewFit("width");
              setPreviewZoom(1);
            }}
            type="button"
          >{copy.fitWidth}</button>
          <button
            className="heading-action"
            disabled={!documentOpen}
            onClick={renderSelectedPage}
            type="button"
          >{copy.render}</button>
          </>} compact={<>
            {currentPageCache && <span>{copy.page} {selectedPage + 1} / {currentPageCache.pageCount}</span>}
            <button aria-label={copy.zoomOut} disabled={previewZoom <= 0.5}
              onClick={() => setPreviewZoom(zoom => Math.max(0.5, zoom - 0.25))} type="button">−</button>
            <span>{copy.zoomPercent(Math.round(previewZoom * 100))}</span>
            <button aria-label={copy.zoomIn} disabled={previewZoom >= 4}
              onClick={() => setPreviewZoom(zoom => Math.min(4, zoom + 0.25))} type="button">+</button>
            <ActionMenu label={copy.viewMenu} actions={[
              {label: copy.fitPage, disabled: !displayedPreview,
                run: () => { setPreviewFit("page"); setPreviewZoom(1); }},
              {label: copy.fitWidth, run: () => { setPreviewFit("width"); setPreviewZoom(1); }},
              {label: copy.zoomOut, disabled: previewZoom <= 0.5,
                run: () => setPreviewZoom(zoom => Math.max(0.5, zoom - 0.25))},
              {label: copy.zoomIn, disabled: previewZoom >= 4,
                run: () => setPreviewZoom(zoom => Math.min(4, zoom + 0.25))},
              {label: copy.prevPageMenu, disabled: !currentPageCache || selectedPage <= 0,
                run: () => selectPage(selectedPage - 1)},
              {label: copy.nextPageMenu,
                disabled: !currentPageCache || selectedPage + 1 >= currentPageCache.pageCount,
                run: () => selectPage(selectedPage + 1)},
            ]}/>
            <button className="heading-action" disabled={!documentOpen}
              onClick={renderSelectedPage} type="button">{copy.render}</button>
          </>}/>
      </div>
      <div className="preview-canvas" onClick={selectPreviewAnchor} ref={previewCanvasRef}>
        {previewUrl && displayedPreview
          ? (
            <div
              className="preview-image-stage"
              style={{
                width: `${previewScale * 100}%`,
                aspectRatio: `${displayedPreview.rendered.page_width} / ${displayedPreview.rendered.page_height}`,
              }}
            >
              <img
                alt={copy.renderedScore(displayedPreview.page + 1)}
                height={displayedPreview.rendered.page_height}
                onError={() => previewImageSettled(true)}
                onLoad={() => previewImageSettled(false)}
                ref={previewImageRef}
                width={displayedPreview.rendered.page_width}
                src={previewUrl}
              />
              {highlightPage && cursorAnchor && cursorRowBounds && (
                <span
                  aria-hidden="true"
                  className="cursor-row-highlight"
                  style={{
                    top: `${(cursorRowBounds.top / highlightPage.page_height) * 100}%`,
                    height: `${((cursorRowBounds.bottom - cursorRowBounds.top) / highlightPage.page_height) * 100}%`,
                  }}
                />
              )}
              {highlightPage && cursorAnchor && (
                <span
                  aria-hidden="true"
                  className="cursor-anchor"
                  ref={cursorMarkerRef}
                  style={{
                    left: `${(cursorAnchor.x / highlightPage.page_width) * 100}%`,
                    top: `${(cursorAnchor.y / highlightPage.page_height) * 100}%`,
                  }}
                />
              )}
            </div>
          )
          : <p>{copy.noPreview}</p>}
      </div>
      <div aria-live="polite" className="status-line" role="status">
        {statusText(status, copy)}
      </div>
      {displayedPreview && !previewIsCurrent && (
        <p aria-live="polite" className="stale-preview" role="status">{copy.previewStale}</p>
      )}
      {previewIsCurrent && currentPage?.custom_markup_omitted && (
        <p aria-live="polite" className="stale-preview" role="status">
          {copy.customMarkupOmitted}
        </p>
      )}
      {previewIsCurrent && diagnostics.length > 0 && (
        <ul aria-label={copy.diagnostics} className="diagnostics">
          {diagnostics.map((item, index) => (
            <li key={`${item.code}-${index}`}>
              <button
                className="diagnostic-jump"
                disabled={!item.span}
                onClick={() => jumpToDiagnostic(item)}
                title={`${item.code}${item.recovery ? ` — ${item.recovery}` : ""}`}
                type="button"
              >
                <span className={`diagnostic-severity diagnostic-${item.severity}`}>
                  {item.severity}
                </span>
                {item.span && (
                  <span className="diagnostic-pos">
                    {item.span.start.line}:{item.span.start.column}
                  </span>
                )}
                <span className="diagnostic-message">{item.message}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
