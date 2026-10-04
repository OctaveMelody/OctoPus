import { useEffect, useMemo, useRef, useState } from "react";
import type { Dispatch, MouseEvent, RefObject, SetStateAction } from "react";
import type { JpsEditorHandle } from "../editor/JpsEditor";
import { createLatestPreviewQueue } from "./preview-queue.js";
import {
  cacheRenderedPage,
  pageFitScale,
  PageOutOfRangeError,
  renderPagesProgressively,
  svgPreviewDataUrl,
} from "./preview-pages.js";
import {
  createSourceOffsetMap,
  findSourceAnchor,
  hitTestSourceAnchor,
  imagePointToSvg,
} from "./source-mapping.js";
import type { DocumentSnapshot, FocusPane, PageCache, PageRenderResponse, PreviewQueue,
  PreviewRequest, RenderDiagnostic, RenderDiagnostics, RenderedPage, SourceAnchor, Status,
  WorkspaceCopy, FontSources } from "./types";

export function useScorePreview({ score, currentDocument, documentOpen, recoveryReady, copy,
  setStatus, editorController, focusPane, setFocusPane, fontSources }: {
  fontSources?: FontSources;
  score: DocumentSnapshot;
  currentDocument: RefObject<DocumentSnapshot>;
  documentOpen: boolean;
  recoveryReady: boolean;
  copy: WorkspaceCopy;
  setStatus: Dispatch<SetStateAction<Status>>;
  editorController: RefObject<JpsEditorHandle | null>;
  focusPane: FocusPane;
  setFocusPane: Dispatch<SetStateAction<FocusPane>>;
}) {
  const copyRef = useRef(copy);
  copyRef.current = copy;
  const revision = score.revision;
  const renderStarted = useRef(0);
  const renderElapsed = useRef<number | undefined>(undefined);
  const previewQueue = useRef<PreviewQueue | null>(null);
  const cursorMarkerRef = useRef<HTMLSpanElement>(null);
  const previewImageRef = useRef<HTMLImageElement>(null);
  const [previewUrl, setPreviewUrl] = useState("");
  const sourceOffsetMap = useMemo(() => createSourceOffsetMap(score.source), [score.source]);
  const sourceOffsetMapRef = useRef(sourceOffsetMap);
  sourceOffsetMapRef.current = sourceOffsetMap;
  const [pageCache, setPageCache] = useState<PageCache | null>(null);
  const [selectedPage, setSelectedPage] = useState(0);
  const currentPageCache = pageCache?.documentId === score.id && pageCache.revision === revision
    ? pageCache
    : null;
  const currentPage = currentPageCache?.pages.get(selectedPage) ?? null;
  const selectedPageRef = useRef(selectedPage);
  selectedPageRef.current = selectedPage;
  const pageCacheRef = useRef<PageCache | null>(null);
  const editorCursor = useRef<{ offset: number; focused: boolean }>({ offset: 0, focused: false });
  const followEditorCursor = useRef(true);
  const selectingPreviewAnchor = useRef(false);
  const [cursorAnchor, setCursorAnchor] = useState<SourceAnchor | null>(null);
  const [previewZoom, setPreviewZoom] = useState(1);
  const [previewFit, setPreviewFit] = useState<"page" | "width">("width");
  const previewCanvasRef = useRef<HTMLDivElement>(null);
  const [previewCanvasSize, setPreviewCanvasSize] = useState({ width: 0, height: 0 });
  const [diagnostics, setDiagnostics] = useState<RenderDiagnostics>([]);
  const [displayedPreview, setDisplayedPreview] = useState<{
    documentId: string;
    revision: number;
    page: number;
    rendered: RenderedPage;
  } | null>(null);
  useEffect(() => {
    const element = previewCanvasRef.current;
    if (!element) return;
    const updateSize = () => {
      const styles = getComputedStyle(element);
      setPreviewCanvasSize({
        width: element.clientWidth - parseFloat(styles.paddingLeft) - parseFloat(styles.paddingRight),
        height: element.clientHeight - parseFloat(styles.paddingTop) - parseFloat(styles.paddingBottom),
      });
    };
    const observer = new ResizeObserver(updateSize);
    updateSize();
    observer.observe(element);
    return () => observer.disconnect();
  }, [recoveryReady]);

  function refreshCursorAnchor(cache: PageCache | null = pageCacheRef.current) {
    const current = currentDocument.current;
    if (
      !cache
      || cache.documentId !== current.id
      || cache.revision !== current.revision
    ) {
      setCursorAnchor(null);
      return;
    }
    const offset = sourceOffsetMapRef.current.utf16ToCodePoint(editorCursor.current.offset);
    const position = offset === null
      ? null
      : sourceOffsetMapRef.current.codePointToPosition(offset);
    const anchor = offset === null
      ? null
      : findSourceAnchor(
        cache.pages,
        offset,
        cache.pages.size === cache.pageCount ? position : null,
      ) as SourceAnchor | null;
    setCursorAnchor(anchor);
    if (anchor?.pageIndex !== undefined && anchor.pageIndex !== selectedPageRef.current) {
      selectedPageRef.current = anchor.pageIndex;
      setSelectedPage(anchor.pageIndex);
    }
  }

  function acceptRenderedPage(requested: PreviewRequest, page: RenderedPage) {
    if (
      currentDocument.current.id !== requested.document.id
      || currentDocument.current.revision !== requested.document.revision
    ) return;
    const next = cacheRenderedPage(pageCacheRef.current, requested.document, page);
    pageCacheRef.current = next;
    setPageCache(next);
    if (selectedPageRef.current >= page.page_count) {
      const clamped = page.page_count - 1;
      selectedPageRef.current = clamped;
      setSelectedPage(clamped);
    }
    refreshCursorAnchor(next);
  }

  useEffect(() => {
    pageCacheRef.current = null;
    setPageCache(null);
    const queue = createLatestPreviewQueue<PreviewRequest, RenderedPage>(
      (request: PreviewRequest, report, isLatest) => {
        const invokePage = (requestedDocument: DocumentSnapshot, pageIndex: number) => {
          const tauri = window.__TAURI__;
          if (!tauri) throw new Error(copyRef.current.needsDesktop);
          return tauri.core.invoke<PageRenderResponse>("render_score_page", {
            args: {
              documentId: requestedDocument.id,
              documentRevision: requestedDocument.revision,
              name: requestedDocument.name,
              code: requestedDocument.source,
              customCode: requestedDocument.customCode,
              pageConfig: { ...requestedDocument.pageConfig, ...(fontSources ? { _font_sources: fontSources } : {}) },
              pageIndex,
            },
          });
        };
        return renderPagesProgressively(request, invokePage, report, isLatest);
      },
      {
        isCurrent: ({ document }) => (
          currentDocument.current.id === document.id
          && currentDocument.current.revision === document.revision
        ),
        onStart: () => {renderStarted.current = performance.now(); renderElapsed.current = undefined; setStatus({kind: "rendering"});},
        onProgress: (request, page) => {
          acceptRenderedPage(request, page);
          setStatus({kind: "rendering", completed: pageCacheRef.current?.pages.size ?? 0, pages: page.page_count});
        },
        onResult: (_request, page) => {
          renderElapsed.current = performance.now() - renderStarted.current;
          setStatus({kind: "rendered", pages: page.page_count, elapsed: renderElapsed.current});
        },
        onError: (_request, error) => {
          if (error instanceof PageOutOfRangeError) {
            if (error.pageCount > 0) {
              const clamped = error.pageCount - 1;
              selectedPageRef.current = clamped;
              setSelectedPage(clamped);
            }
            setStatus({
              kind: "error",
              message: error.pageCount === 0
                ? copyRef.current.emptyRenderResult
                : copyRef.current.pageChanged,
            });
            return;
          }
          setStatus({
            kind: "error",
            message: error instanceof Error ? error.message : String(error),
          });
        },
      },
    );
    previewQueue.current = queue;
    return () => {
      queue.dispose();
      if (previewQueue.current === queue) previewQueue.current = null;
    };
  }, [JSON.stringify(fontSources)]);

  useEffect(() => {
    if (!documentOpen) return;
    const cache = pageCacheRef.current;
    if (
      cache?.documentId === score.id
      && cache.revision === revision
      && cache.pages.has(selectedPage)
    ) return;
    previewQueue.current?.request({ document: score, pageIndex: selectedPage }, { immediate: true });
  }, [documentOpen, score.id, revision, selectedPage, JSON.stringify(fontSources)]);

  useEffect(() => {
    if (!currentPage) return;
    setDiagnostics(currentPage.diagnostics);
    setPreviewUrl(svgPreviewDataUrl(currentPage.svg));
    setDisplayedPreview({
      documentId: score.id,
      revision,
      page: selectedPage,
      rendered: currentPage,
    });
  }, [currentPage, score.id, revision, selectedPage]);

  const previewIsCurrent = currentPage !== null
    && displayedPreview?.documentId === score.id
    && displayedPreview.revision === revision
    && displayedPreview.page === selectedPage;
  useEffect(() => {
    // An unchanged cached SVG does not fire another load event after Refresh.
    const image = previewImageRef.current;
    if (image?.complete) previewImageSettled(image.naturalWidth === 0);
  }, [displayedPreview, previewUrl]);
  const previewFitScale = previewFit === "page"
    && displayedPreview
    && previewCanvasSize.width > 0
    && previewCanvasSize.height > 0
    && displayedPreview.rendered.page_width > 0
    && displayedPreview.rendered.page_height > 0
    ? pageFitScale(previewCanvasSize, displayedPreview.rendered)
    : 1;
  const previewScale = previewZoom * previewFitScale;
  const highlightPage = previewIsCurrent
    && displayedPreview
    && cursorAnchor?.pageIndex === selectedPage
    ? displayedPreview.rendered
    : null;
  const cursorRowYValues = highlightPage && cursorAnchor?.row !== undefined
    ? [
        ...highlightPage.events
          .filter((event) => event.row === cursorAnchor.row)
          .map((event) => event.y),
        ...highlightPage.lyrics
          .filter((lyric) => lyric.row === cursorAnchor.row)
          .map((lyric) => lyric.y),
      ]
    : [];
  const cursorRowBounds = cursorRowYValues.length > 0 && highlightPage
    ? {
        top: Math.max(0, Math.min(...cursorRowYValues) - 14),
        bottom: Math.min(highlightPage.page_height, Math.max(...cursorRowYValues) + 14),
      }
    : null;

  useEffect(() => {
    if (previewIsCurrent && followEditorCursor.current) {
      cursorMarkerRef.current?.scrollIntoView({ block: "center", inline: "nearest" });
    }
  }, [cursorAnchor, previewFitScale, previewIsCurrent, previewZoom, selectedPage]);

  function handleEditorCursor(offset: number, focused: boolean) {
    if (focused && !selectingPreviewAnchor.current) followEditorCursor.current = true;
    editorCursor.current = { offset, focused };
    refreshCursorAnchor();
  }

  function jumpToDiagnostic(item: RenderDiagnostic) {
    if (!item.span) return;
    const from = sourceOffsetMapRef.current.codePointToUtf16(item.span.start.offset);
    const to = sourceOffsetMapRef.current.codePointToUtf16(item.span.end.offset);
    if (from === null || to === null) return;
    const selectSpan = () => editorController.current?.selectSourceRange(from, to, false);
    if (focusPane === "preview") {
      setFocusPane("editor");
      window.requestAnimationFrame(selectSpan);
    } else {
      selectSpan();
    }
  }

  function selectPage(pageIndex: number) {
    if (!currentPageCache) return;
    const page = Math.max(0, Math.min(currentPageCache.pageCount - 1, pageIndex));
    selectedPageRef.current = page;
    setSelectedPage(page);
  }

  function renderSelectedPage() {
    const queue = previewQueue.current;
    if (!queue) {
      setStatus({ kind: "error", message: copy.previewNotReady });
      return;
    }
    queue.request({
      document: currentDocument.current,
      pageIndex: selectedPageRef.current,
    }, { immediate: true });
  }

  function selectPreviewAnchor(event: MouseEvent<HTMLDivElement>) {
    if (!previewIsCurrent || !displayedPreview) return;
    const stage = event.currentTarget.querySelector(".preview-image-stage");
    if (!stage || !stage.contains(event.target as Node)) return;
    const page = displayedPreview.rendered;
    const point = imagePointToSvg(
      stage.getBoundingClientRect(),
      page.page_width,
      page.page_height,
      event.clientX,
      event.clientY,
    );
    if (!point) return;
    const anchor = hitTestSourceAnchor(page, point.x, point.y);
    if (!anchor?.sourceSpans.length) return;
    const start = Math.min(...anchor.sourceSpans.map((span) => span.start.offset));
    const end = Math.max(...anchor.sourceSpans.map((span) => span.end.offset));
    const offsets = sourceOffsetMapRef.current;
    const from = offsets.codePointToUtf16(start);
    const to = offsets.codePointToUtf16(end);
    if (from === null || to === null) return;
    // Programmatic editor focus/selection must not feed back into preview scrolling.
    followEditorCursor.current = false;
    selectingPreviewAnchor.current = true;
    try {
      editorController.current?.selectSourceRange(from, to);
    } finally {
      selectingPreviewAnchor.current = false;
    }
  }

  function resetPreview(nextDocument: DocumentSnapshot) {
    previewQueue.current?.invalidate();
    sourceOffsetMapRef.current = createSourceOffsetMap(nextDocument.source);
    editorCursor.current = { offset: 0, focused: false };
    followEditorCursor.current = true;
    setCursorAnchor(null);
    pageCacheRef.current = null;
    setPageCache(null);
    setSelectedPage(0);
    selectedPageRef.current = 0;
    setDiagnostics([]);
    setDisplayedPreview(null);
    setPreviewUrl("");
  }

  function sourceChanged(source: string) {
    sourceOffsetMapRef.current = createSourceOffsetMap(source);
  }

  function previewImageSettled(failed: boolean) {
    if (displayedPreview
      && currentDocument.current.id === displayedPreview.documentId
      && currentDocument.current.revision === displayedPreview.revision
      && selectedPageRef.current === displayedPreview.page) {
      if (failed) setStatus({kind: "error", message: copyRef.current.previewDisplayFailed});
      else if (pageCacheRef.current?.pages.size === displayedPreview.rendered.page_count) {
        setStatus({kind: "rendered", pages: displayedPreview.rendered.page_count, elapsed: renderElapsed.current});
      }
    }
  }

  return { currentPageCache, currentPage, selectedPage, previewZoom, setPreviewZoom, setPreviewFit,
    displayedPreview, previewScale, previewIsCurrent, previewUrl, previewCanvasRef, previewImageRef,
    cursorMarkerRef,
    highlightPage, cursorAnchor, cursorRowBounds, diagnostics, handleEditorCursor, jumpToDiagnostic,
    selectPage, renderSelectedPage, selectPreviewAnchor, resetPreview, sourceChanged, previewImageSettled };
}
