import { useEffect, useRef, useState } from "react";
import type { CSSProperties, ReactNode } from "react";

import { PanelDivider } from "./PanelDivider";
import { AdaptiveToolbar } from "./AdaptiveToolbar";
import { ActionMenu } from "./ActionMenu";
import { checkForUpdate, openHelpDestination } from "./help-actions.js";
import type { HelpDestination, UpdateResult } from "./help-actions.js";

import { JpsEditor, type JpsEditorHandle } from "../editor/JpsEditor";
import { LifecycleDialogs } from "./LifecycleDialogs";
import { InformationDialog } from "./InformationDialog";
import { PageSettings } from "./PageSettings";
import { ReferencePanel } from "../reference/ReferencePanel";
import { messages } from "./i18n";
import brandMark from "./octopus.svg";
import {useDocumentLifecycle, useRecoveryPersistence} from "./useDocumentLifecycle";
import {getStorage} from "./workspace-storage.js";
import { useScorePreview } from "./useScorePreview";
import { ScorePreview } from "./ScorePreview";
import { exportStatusText, useScoreExports } from "./useScoreExports";
import {useSourceDiagnostics} from "./useSourceDiagnostics";
import {useTranscriptionSession, type TranscriptionContext} from "./useTranscriptionSession";
import {normalizedIssueRegions, issueSourceRange, mapFormattedIssueSpans} from "./transcription-review.js";
import {createSourceOffsetMap} from "./source-mapping.js";
import { useReferenceAssets } from "./useReferenceAssets";
import type {
  WorkspacePreferences,
  WorkspaceMode,
  LayoutId,
  PaneId,
  FocusPane,
  EngineCapabilities,
  TranscriptionIssue,
  Status,
} from "./types";
import {
  isDocumentDirty,
  isPageConfigDirty,
  updateDocumentPageConfig,
  updateDocumentSource,
} from "./document.js";
import { getEngineCapabilities } from "./native-files.js";
import {
  selectReferenceImage,
  updateReferenceView,
} from "./reference-set.js";
import { defaultPreferences, readPreferences, writePreferences } from "./preferences.js";

function AppBrand({ label, onOpen }: { label: string; onOpen: () => void }) {
  return (
    <a aria-label={label} className="app-brand" href="https://github.com/OctaveMelody/OctoPus"
      onClick={event => { event.preventDefault(); onOpen(); }}>
      <img alt="" className="brand-mark" height="40" src={brandMark} width="40" />
      <span className="brand-type">
        <span className="brand-name">Octo<span>Pus</span></span>
        <span className="brand-studio">by <strong>OctaveMelody</strong></span>
      </span>
    </a>
  );
}

export function App() {
  const [preferences, setPreferences] = useState<WorkspacePreferences>(() => {
    const storage = getStorage();
    return storage
      ? readPreferences(storage, window.navigator.language)
      : defaultPreferences(window.navigator.language);
  });
  const [focusPane, setFocusPane] = useState<FocusPane>(null);
  const [editorHistory, setEditorHistory] = useState({ undo: false, redo: false });
  const [engineCapabilities, setEngineCapabilities] = useState<EngineCapabilities>({
    ocr: false,
    png_export: false,
  });
  const [transcriptionIssues, setTranscriptionIssues] = useState<TranscriptionIssue[]>([]);
  const [reviewSource, setReviewSource] = useState<{id: string; source: string; context: TranscriptionContext} | null>(null);
  const [reviewRegion, setReviewRegion] = useState<{id: string; boxes: number[][]; serial: number} | null>(null);
  const editorController = useRef<JpsEditorHandle | null>(null);
  const [status, setStatus] = useState<Status>({ kind: "ready" });
  const [checkingUpdate, setCheckingUpdate] = useState(false);
  const [updateResult, setUpdateResult] = useState<UpdateResult | null>(null);
  const [updateError, setUpdateError] = useState("");
  const [browserError, setBrowserError] = useState("");
  const [informationDialog, setInformationDialog] = useState<"about" | "update" | "browser-error" | null>(null);
  const exportMenuRef = useRef<HTMLDetailsElement>(null);
  const findMenuRef = useRef<HTMLDetailsElement>(null);
  const transcriptionMenuRef = useRef<HTMLDetailsElement>(null);
  const informationDialogRef = useRef<HTMLDialogElement>(null);
  const appShortcutRef = useRef<(event: KeyboardEvent) => void>(() => {});
  const copy = messages[preferences.language];
  const copyRef = useRef(copy);
  copyRef.current = copy;
  const lifecycle = useDocumentLifecycle({copyRef, setStatus, setPreferences, setFocusPane,
    editorController, getServices: () => ({referenceAssets, resetPreview, bindReview,
      clearReview: () => {setTranscriptionIssues([]); setReviewSource(null); setReviewRegion(null);},
      isTranscribing: () => transcribing.current})});
  const {score, setScore, currentDocument, documentOpen, setActiveDialog, activeDialogRef,
    setDialogError, settingsDraftRef, settingsDraftReset, isSaving, saving, recoveryReady,
    recoveryReadyRef, recoverySequence, currentRecoveryDraft, requestAction, requestNativeClose,
    saveDocument} = lifecycle;
  const transcription = useTranscriptionSession({currentDocument,
    getReferences: () => currentReferences.current, copyRef,
    isBusy: mode => saving.current || referenceAssets.isImporting() || (mode === "append" && !documentOpen),
    onDraft: adoptTranscription,
    onError: message => setStatus({kind: "error", message}),
  });
  const {transcribing, isTranscribing, isCancelling, progress: transcriptionProgress, cancelTranscription} = transcription;
  const sourceDiagnostics = useSourceDiagnostics({score, enabled: documentOpen && recoveryReady,
    errorMessage: copy.sourceDiagnosticsFailed});
  useEffect(() => {if (isTranscribing) setStatus({kind: "transcribing"});}, [isTranscribing]);
  const reviewIsCurrent = reviewSource?.id === score.id && reviewSource.source === score.source;
  const offsetMap = createSourceOffsetMap(score.source);
  const noteDiagnostics = reviewIsCurrent ? transcriptionIssues.flatMap(issue => {
    if (issue.source_start == null || issue.source_end == null) return [];
    const start = offsetMap.codePointToPosition(issue.source_start);
    const end = offsetMap.codePointToPosition(issue.source_end);
    return start && end ? [{code: issue.code, message: issue.detail, severity: "warning",
      span: {start: {...start, offset: issue.source_start}, end: {...end, offset: issue.source_end}}}] : [];
  }) : [];
  const outputFontSources = Object.fromEntries(Object.entries(preferences.fontSources).map(
    ([role, source]) => [role, engineCapabilities.fonts?.[role]?.available ? source : "fallback"],
  ));
  const { isExporting, currentExportStatus, startExport } = useScoreExports({
    score, currentDocument, documentOpen, copyRef, fontSources: outputFontSources });
  const referenceAssets = useReferenceAssets({ currentDocument, recoverySequence,
    currentRecoveryDraft, copyRef, setStatus, setActiveDialog, setDialogError, setPreferences,
    externalImportBusy: () => !recoveryReadyRef.current || saving.current || transcribing.current
      || activeDialogRef.current !== null || Boolean(informationDialogRef.current?.open) });
  const { referenceDropActive, references, referenceSources, currentReferences, pendingReferenceImport,
    isImportingReferences, isCommittingReferences, isHandlingReferenceChoice,
    importReferences, updateReferences } = referenceAssets;

  const preview = useScorePreview({ score, currentDocument, documentOpen, recoveryReady, copy,
    setStatus, editorController, focusPane, setFocusPane, fontSources: outputFontSources });
  const { handleEditorCursor, resetPreview, sourceChanged } = preview;
  useRecoveryPersistence(lifecycle, referenceAssets, setStatus);

  const layout: LayoutId = preferences.mode === "normal"
    ? preferences.normalLayout
    : preferences.transcriptionLayout;
  const split = preferences.splits[layout];
  const xLabel = layout === "T1" || layout === "T2" ? copy.referenceWidth : copy.firstPaneWidth;
  const yLabel = layout === "N2"
    ? copy.previewHeight
    : layout === "T1"
      ? copy.editorPaneWidth
      : copy.comparisonHeight;

  useEffect(() => {
    const closeMenusOnOutsideClick = (event: globalThis.MouseEvent) => {
      if (!(event.target instanceof Node)) return;
      for (const menu of [exportMenuRef.current,
        transcriptionMenuRef.current, findMenuRef.current]) {
        if (menu?.open && !menu.contains(event.target)) menu.open = false;
      }
    };
    document.addEventListener("click", closeMenusOnOutsideClick);
    return () => document.removeEventListener("click", closeMenusOnOutsideClick);
  }, []);

  function requestTranscription(mode: "new" | "append") {
    if (transcriptionMenuRef.current) transcriptionMenuRef.current.open = false;
    void transcription.requestTranscription(mode);
  }

  function bindReview(context: TranscriptionContext, issues = context.draft.issues) {
    setTranscriptionIssues(issues);
    setReviewSource({id: currentDocument.current.id, source: currentDocument.current.source, context});
    setReviewRegion(null);
  }

  function adoptTranscription(mode: "new" | "append", context: TranscriptionContext) {
    const {draft} = context;
    if (mode === "new") {
      lifecycle.prepareTranscription(context);
      return;
    }
    const editor = editorController.current;
    if (!editor) throw new Error(copyRef.current.transcriptionEditorUnavailable);
    const existing = currentDocument.current.source;
    const musicStart = draft.jps.search(/^Q\d*(?:\[[^\]\r\n]*\]|"[^"\r\n]*")?:/im);
    if (musicStart < 0) throw new Error(copyRef.current.transcriptionNoMusic);
    const prefix = !existing.trim() ? "" : /\[fenye\]\s*$/.test(existing)
      ? "\n" : existing.endsWith("\n") ? "\n[fenye]\n" : "\n\n[fenye]\n";
    const addition = prefix + (existing.trim() ? "\n" + draft.jps.slice(musicStart).trimEnd() : draft.jps.trimEnd()) + "\n";
    const removed = existing.trim() ? Array.from(draft.jps.slice(0, musicStart)).length : 0;
    const shift = Array.from(existing + prefix + (existing.trim() ? "\n" : "")).length - removed;
    const issues = draft.issues.map(issue => ({...issue,
      source_start: issue.source_start != null && issue.source_start >= removed ? issue.source_start + shift : null,
      source_end: issue.source_end != null && issue.source_end >= removed ? issue.source_end + shift : null,
    }));
    editor.appendSource(addition);
    bindReview(context, mapFormattedIssueSpans(existing + addition, currentDocument.current.source, issues));
    setStatus({kind: "transcribed", issues: issues.length});
    setFocusPane(null);
  }

  function reviewIssue(issue: TranscriptionIssue) {
    if (!reviewSource) return;
    const id = reviewSource.context.pages[issue.page - 1];
    if (id && currentReferences.current.images.some(page => page.id === id)) {
      updateReferences(selectReferenceImage(currentReferences.current, id));
      const boxes = normalizedIssueRegions(issue.regions, reviewSource.context.draft.page_dimensions?.[issue.page - 1]);
      setReviewRegion({id, boxes, serial: Date.now()});
      setPreferences(current => ({...current, mode: "transcription"}));
      setFocusPane(null);
    }
    if (reviewSource.id === score.id && reviewSource.source === score.source) {
      const range = issueSourceRange(score.source, issue);
      if (range) editorController.current?.selectSourceRange(range.from, range.to, false);
    }
  }

  useEffect(() => {
    document.documentElement.lang = preferences.language;
  }, [preferences.language]);

  useEffect(() => {
    let active = true;
    void Promise.resolve()
      .then(() => getEngineCapabilities())
      .then((capabilities) => {
        if (
          active
          && typeof capabilities.ocr === "boolean"
          && typeof capabilities.png_export === "boolean"
        ) {
          setEngineCapabilities(capabilities);
          setPreferences(current => ({ ...current, fontSources: Object.fromEntries(
            Object.entries(current.fontSources).map(([role, source]) =>
              [role, capabilities.fonts?.[role]?.available ? source : "fallback"])
          ) }));
        }
      })
      .catch(() => {});
    return () => { active = false; };
  }, []);

  useEffect(() => {
    const dialog = informationDialogRef.current;
    if (!dialog) return;
    if (informationDialog && !dialog.open) dialog.showModal();
    else if (!informationDialog && dialog.open) dialog.close();
  }, [informationDialog]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => appShortcutRef.current(event);
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  useEffect(() => {
    const storage = getStorage();
    if (!storage || !writePreferences(storage, preferences)) setStatus({ kind: "preferences" });
  }, [preferences]);

  function changeMode(mode: WorkspaceMode) {
    setFocusPane(null);
    setPreferences((current) => ({ ...current, mode }));
  }

  function changeLayout(nextLayout: LayoutId) {
    setFocusPane(null);
    setPreferences((current) => current.mode === "normal"
      ? { ...current, normalLayout: nextLayout === "N2" ? "N2" : "N1" }
      : { ...current, transcriptionLayout: nextLayout === "T1" ? "T1" : "T2" });
  }

  function changeSplit(nextSplit: { x: number; y: number }) {
    setPreferences((current) => ({
      ...current, splits: { ...current.splits, [layout]: nextSplit },
    }));
  }

  const layoutOptions = preferences.mode === "normal"
    ? [
        { value: "N1", label: copy.normalSideBySide },
        { value: "N2", label: copy.normalStacked },
      ]
    : [
        { value: "T1", label: copy.transcriptionColumns },
        { value: "T2", label: copy.transcriptionComparison },
      ];
  const setSplitStyle = {
    "--split-x": `${split.x}fr`,
    "--split-y": `${split.y}fr`,
    "--split-rest-x": `${100 - split.x}fr`,
    "--split-rest-y": `${100 - split.y}fr`,
    "--split-rest-t1": `${100 - split.x - split.y}fr`,
  } as CSSProperties;
  function toggleFullscreen() {
    const core = window.__TAURI__?.core;
    if (core) {
      void core.invoke("toggle_window_maximize").catch(() => {});
      return;
    }
    if (document.fullscreenElement === null) {
      void document.documentElement.requestFullscreen().catch(() => {});
    } else {
      void document.exitFullscreen().catch(() => {});
    }
  }

  function positionFindMenu(menu: HTMLDetailsElement | null) {
    if (!menu?.open) return;
    const anchor = menu.querySelector("summary")!.getBoundingClientRect();
    const popup = menu.querySelector<HTMLElement>(".find-menu-items")!;
    const panel = menu.closest(".editor-panel")!.getBoundingClientRect();
    popup.style.left = `${Math.max(panel.left + 8, Math.min(anchor.left, panel.right - popup.offsetWidth - 8))}px`;
    popup.style.top = `${anchor.bottom + 4}px`;
  }

  async function openHelp(destination: HelpDestination) {
    try {
      await openHelpDestination(destination, preferences.language);
    } catch (error) {
      setBrowserError(error instanceof Error ? error.message : String(error));
      setInformationDialog("browser-error");
    }
  }

  async function checkUpdates() {
    if (checkingUpdate) return;
    setInformationDialog("update");
    setCheckingUpdate(true);
    setUpdateResult(null);
    setUpdateError("");
    try {
      setUpdateResult(await checkForUpdate());
    } catch (error) {
      setUpdateError(error instanceof Error ? error.message : String(error));
    } finally {
      setCheckingUpdate(false);
    }
  }

  function editClipboard(action: "cut" | "copy" | "paste") {
    try {
      if (!editorController.current?.[action]()) throw new Error(copy.clipboardUnavailable);
    } catch {
      setStatus({ kind: "error", message: copy.clipboardUnavailable });
    }
  }

  const referenceOperationBusy = isImportingReferences
    || pendingReferenceImport !== null
    || isHandlingReferenceChoice
    || isCommittingReferences
    || isTranscribing;
  const referencePanelImages = references.images.map((image) => ({
    ...image,
    src: image.kind === "pdf-page"
      ? referenceSources[image.pdfId] ?? null
      : referenceSources[image.id] ?? null,
  }));
  const isMac = /Mac/i.test(navigator.platform);
  const shortcut = (key: string) => `${isMac ? "⌘" : "Ctrl+"}${key}`;
  const replaceShortcut = isMac ? "⌘+⌥+F" : "Ctrl+H";
  const panes: Record<PaneId, ReactNode> = {
    editor: (
      <section aria-label={copy.source} className="panel editor-panel" key="editor">
        <div className="panel-heading">
          <div className="editor-heading-title">
            <h2>{copy.source}</h2>
          </div>
          <AdaptiveToolbar label={copy.editorTools} className="editor-heading-tools"
            expanded={<>
            <button disabled={!documentOpen || !editorHistory.undo} title={`${copy.undo} (${shortcut("Z")})`} onClick={() => editorController.current?.undo()} type="button">
              {copy.undo}
            </button>
            <button disabled={!documentOpen || !editorHistory.redo} title={`${copy.redo} (${shortcut(isMac ? "Shift+Z" : "Y")})`} onClick={() => editorController.current?.redo()} type="button">
              {copy.redo}
            </button>
            <button disabled={!documentOpen} onClick={() => editClipboard("cut")} type="button">
              {copy.cut}
            </button>
            <button disabled={!documentOpen} onClick={() => editClipboard("copy")} type="button">
              {copy.copy}
            </button>
            <button disabled={!documentOpen} onClick={() => editClipboard("paste")} type="button">
              {copy.paste}
            </button>
            <details className="find-menu" ref={findMenuRef} onToggle={(event) => positionFindMenu(event.currentTarget)} onKeyDown={(event) => {
              if (event.key === "Escape") {
                event.currentTarget.open = false;
                event.currentTarget.querySelector("summary")?.focus();
              }
            }}>
              <summary aria-disabled={!documentOpen} title={`${copy.find} (${shortcut("F")})`} onClick={(event) => {
                event.preventDefault();
                const menu = findMenuRef.current;
                if (!documentOpen || !menu) return;
                menu.open = !menu.open;
                positionFindMenu(menu);
              }}>{copy.find}</summary>
              <div className="find-menu-items" role="group" aria-label={copy.find}>
                {[false, true].map((replace) => (
                  <button key={String(replace)} disabled={!documentOpen} onClick={() => {
                    if (findMenuRef.current) findMenuRef.current.open = false;
                    editorController.current?.find(replace);
                  }} type="button" title={`${replace ? copy.findReplace : copy.find} (${replace ? replaceShortcut : shortcut("F")})`}>{replace ? copy.findReplace : copy.find}</button>
                ))}
              </div>
            </details>
            <button disabled={!documentOpen} title={`${copy.selectAll} (${shortcut("A")})`} onClick={() => editorController.current?.selectAll()} type="button">
              {copy.selectAll}
            </button>
            </>} compact={<>
              <ActionMenu label={copy.editMenu} actions={[
                {label: copy.undo, title: `${copy.undo} (${shortcut("Z")})`, disabled: !documentOpen || !editorHistory.undo,
                  run: () => { editorController.current?.undo(); }},
                {label: copy.redo, title: `${copy.redo} (${shortcut(isMac ? "Shift+Z" : "Y")})`, disabled: !documentOpen || !editorHistory.redo,
                  run: () => { editorController.current?.redo(); }},
                ...(["cut", "copy", "paste"] as const).map(action => ({label: copy[action],
                  title: `${copy[action]} (${shortcut({cut:"X",copy:"C",paste:"V"}[action])})`, disabled: !documentOpen, run: () => editClipboard(action)})),
                {label: copy.find, title: `${copy.find} (${shortcut("F")})`, disabled: !documentOpen,
                  run: () => { editorController.current?.find(false); }},
                {label: copy.replaceMenu, title: `${copy.replaceMenu} (${replaceShortcut})`, disabled: !documentOpen,
                  run: () => { editorController.current?.find(true); }},
                {label: copy.selectAll, title: `${copy.selectAll} (${shortcut("A")})`, disabled: !documentOpen,
                  run: () => { editorController.current?.selectAll(); }},
              ]}/>
            </>}/>
          <div className="editor-heading-file">
            {documentOpen && (
              <span className="editor-file-name" title={score.name}>
                {score.name}
              </span>
            )}
            {documentOpen && isDocumentDirty(score) && (
              <span aria-label={copy.unsaved} className="editor-unsaved-flag" title={copy.unsaved}>
                {copy.unsavedFlag}
              </span>
            )}
          </div>
          <button className="heading-action editor-format-action" disabled={!documentOpen} onClick={() => editorController.current?.formatSource()} type="button">
            {copy.formatSource}
          </button>
        </div>
        {documentOpen && <JpsEditor
          diagnostics={[...sourceDiagnostics.diagnostics, ...noteDiagnostics]}
          diagnosticsSource={noteDiagnostics.length > 0 ? score.source : sourceDiagnostics.diagnosticsSource}
          documentId={score.id}
          language={preferences.language}
          onPageConfigChange={(pageConfig) => {
            const nextDocument = updateDocumentPageConfig(currentDocument.current, pageConfig);
            currentDocument.current = nextDocument;
            setScore(nextDocument);
            setStatus({ kind: "changed" });
          }}
          onHistoryChange={(undo, redo) => setEditorHistory((current) => (
            current.undo === undo && current.redo === redo ? current : { undo, redo }
          ))}
          onReady={(handle) => { editorController.current = handle; }}
          onChange={(source) => {
            const nextDocument = updateDocumentSource(currentDocument.current, source);
            currentDocument.current = nextDocument;
            sourceChanged(source);
            setScore(nextDocument);
            setStatus({ kind: "changed" });
          }}
          onCursorChange={handleEditorCursor}
          pageConfig={score.pageConfig}
          source={score.source}
        />}
        {documentOpen && transcriptionIssues.length > 0 && (
          <details className="transcription-review">
            <summary>{copy.transcriptionReview(transcriptionIssues.length)}</summary>
            <ol>
              {transcriptionIssues.map((issue, index) => (
                <li key={`${index}-${issue.code}`}>
                  <button className="transcription-issue" onClick={() => reviewIssue(issue)} type="button">
                    {copy.transcriptionIssuePage(issue.page)}: {issue.detail}
                  </button>
                </li>
              ))}
            </ol>
          </details>
        )}
      </section>
    ),
    preview: <ScorePreview key="preview" preview={preview} copy={copy} documentOpen={documentOpen} status={status} />,
    reference: (
      <ReferencePanel
        key="reference"
        copy={copy}
        dropActive={referenceDropActive}
        images={referencePanelImages}
        busy={referenceOperationBusy}
        importing={isImportingReferences}
        transcribing={isTranscribing}
        cancelling={isCancelling}
        progress={transcriptionProgress}
        onCancel={() => { void cancelTranscription(); setStatus({kind: "ready"}); }}
        reviewRegion={reviewRegion}
        showHint={!preferences.referenceHintDismissed}
        onDismissHint={() => setPreferences(current => ({...current, referenceHintDismissed: true}))}
        transcriptionControl={
          <details className="transcribe-menu" ref={transcriptionMenuRef}>
            <summary title={engineCapabilities.ocr
              ? copy.transcriptionReadyHint
              : copy.transcriptionNoOcr}
            >{copy.transcribe}</summary>
            <div aria-label={copy.transcribe} className="transcribe-menu-items" role="group">
              <button
                disabled={referenceOperationBusy || isSaving || references.images.length === 0}
                onClick={() => { void requestTranscription("new"); }}
                type="button"
              >{copy.transcribeNew}</button>
              <button
                disabled={!documentOpen || referenceOperationBusy || isSaving
                  || references.images.length === 0}
                onClick={() => { void requestTranscription("append"); }}
                type="button"
              >{copy.transcribeAppend}</button>
              <span>{engineCapabilities.ocr
                ? copy.transcriptionReadyHint
                : copy.transcriptionNoOcr}
              </span>
            </div>
          </details>
        }
        renderErrorLabel={copy.pdfRenderFailed}
        visible={!focusPane || focusPane === "reference"}
        onClose={() => changeMode("normal")}
        onImport={() => { void importReferences(); }}
        onSelect={(id) => updateReferences(selectReferenceImage(currentReferences.current, id))}
        onViewChange={(id, patch) => updateReferences(updateReferenceView(currentReferences.current, id, patch))}
        selectedId={references.selectedId}
        views={references.views}
      />
    ),
  };

  const paneOrder: PaneId[] = layout === "N2"
    ? ["preview", "editor"]
    : layout === "T1"
      ? ["reference", "editor", "preview"]
      : layout === "T2"
      ? ["reference", "preview", "editor"]
      : ["editor", "preview"];

  appShortcutRef.current = (event) => {
    if (event.defaultPrevented || activeDialogRef.current !== null || informationDialogRef.current?.open) {
      return;
    }
    if (event.key === "F11") {
      event.preventDefault();
      toggleFullscreen();
      return;
    }
    if (!event.ctrlKey && !event.metaKey) return;
    const key = event.key.toLowerCase();
    const target = event.target as HTMLElement | null;
    const inFormField = target !== null
      && ["INPUT", "SELECT", "TEXTAREA"].includes(target.tagName);
    if (key === "z" || key === "y") {
      if (inFormField) return;
      event.preventDefault();
      if (key === "z" && !event.shiftKey) editorController.current?.undo();
      else editorController.current?.redo();
      return;
    }
    if (key === "n" && !event.shiftKey) {
      event.preventDefault();
      requestAction("new");
    } else if (key === "o" && !event.shiftKey) {
      event.preventDefault();
      requestAction("open");
    } else if (key === "s") {
      event.preventDefault();
      void saveDocument(event.shiftKey);
    }
  };

  if (!recoveryReady) {
    return (
      <main aria-busy="true" className="recovery-loading" role="status">
        {copy.checkingRecovery}
      </main>
    );
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <h1 aria-label={copy.title} className="topbar-title">
          <AppBrand label={copy.projectHome} onOpen={() => { void openHelp("home"); }} />
        </h1>
        <nav aria-label={copy.documentActions} className="document-actions">
          <button disabled={isSaving || referenceOperationBusy} title={`${copy.new} (${shortcut("N")})`} onClick={() => requestAction("new")} type="button">{copy.new}</button>
          <button disabled={isSaving || referenceOperationBusy} title={`${copy.open} (${shortcut("O")})`} onClick={() => requestAction("open")} type="button">{copy.open}</button>
          <button disabled={!documentOpen || isSaving || referenceOperationBusy} title={`${copy.save} (${shortcut("S")})`} onClick={() => { void saveDocument(); }} type="button">{copy.save}</button>
          <button disabled={!documentOpen || isSaving || referenceOperationBusy} title={`${copy.saveAs} (${shortcut("Shift+S")})`} onClick={() => { void saveDocument(true); }} type="button">{copy.saveAs}</button>
          <ActionMenu label={copy.recentFiles} actions={preferences.recentFiles.length
            ? preferences.recentFiles.map(path => ({label: path, disabled: isSaving || referenceOperationBusy,
                run: () => { requestAction("open", path); }}))
            : [{label: copy.noRecentFiles, disabled: true, run: () => {}}]} />
          <details className="export-menu" ref={exportMenuRef}>
            <summary>{copy.exportMenu}</summary>
            <div aria-label={copy.exportOptions} className="export-menu-items">
              <button
                disabled={!documentOpen || isSaving || isExporting || referenceOperationBusy}
                onClick={(event) => startExport(event, "svg")}
                type="button"
              >
                {copy.exportSvg}
              </button>
              <button
                disabled={!documentOpen || isSaving || isExporting || referenceOperationBusy}
                onClick={(event) => startExport(event, "pdf")}
                type="button"
              >
                {copy.exportPdf}
              </button>
              <button
                disabled={!documentOpen || isSaving || isExporting || referenceOperationBusy}
                onClick={(event) => startExport(event, "jpg", 96)}
                type="button"
              >
                {copy.exportJpg}
              </button>
              <button
                disabled={!documentOpen || isSaving || isExporting || referenceOperationBusy}
                onClick={(event) => startExport(event, "jpg", 300)}
                type="button"
              >
                {copy.exportJpg300}
              </button>
              {[96, 300].map(dpi => <button key={`png-${dpi}`}
                disabled={!documentOpen || isSaving || isExporting || referenceOperationBusy || !engineCapabilities.png_export}
                onClick={event => startExport(event, "png", dpi as 96 | 300)} type="button">
                {dpi === 96 ? copy.exportPng : copy.exportPng300}
              </button>)}
            </div>
          </details>
          <button disabled={!documentOpen || isSaving || referenceOperationBusy} onClick={() => requestAction("close-document")} type="button">
            {copy.closeDocument}
          </button>
          <ActionMenu label={copy.helpMenu} title={`${copy.helpMenu} (${copy.fullScreen}: F11)`} actions={[
            {label: copy.userManual, run: () => { void openHelp("manual"); }},
            {label: copy.reportIssues, run: () => { void openHelp("issues"); }},
            {label: copy.submitRequests, run: () => { void openHelp("requests"); }},
            ...(import.meta.env.VITE_UPDATE_CHECK_ENABLED === "false" ? [] : [
              {label: copy.checkForUpdate, disabled: checkingUpdate, run: () => { void checkUpdates(); }},
            ]),
            {label: copy.about, run: () => setInformationDialog("about")},
          ]}/>

          {currentExportStatus && (
            <span
              aria-live={currentExportStatus.kind === "error" ? "assertive" : "polite"}
              className={`export-status${currentExportStatus.kind === "error" ? " error" : ""}`}
              role={currentExportStatus.kind === "error" ? "alert" : "status"}
            >
              {exportStatusText(currentExportStatus, copy)}
            </span>
          )}
        </nav>
        <div className="workspace-actions">
          <button
            disabled={referenceOperationBusy}
            onClick={() => { void importReferences(); }}
            type="button"
          >
            {isImportingReferences ? copy.importingImages : copy.importImage}
          </button>
          <button disabled={isSaving || referenceOperationBusy} onClick={() => requestAction("examples")} type="button">
            {copy.examples}
          </button>
          {documentOpen && (
            <PageSettings
              config={score.pageConfig}
              copy={copy}
              disabled={isSaving}
              key={`${score.id}:${settingsDraftReset}`}
              onApply={(pageConfig) => editorController.current?.applyPageConfig(pageConfig)}
              onDraftChange={(dirty, config) => { settingsDraftRef.current = { dirty, config }; }}
              settingsDirty={isPageConfigDirty(score)}
              wrapped={score.jsonWrapped}
            />
          )}
          <button disabled={isSaving || referenceOperationBusy}
            onClick={() => setActiveDialog("preferences")} type="button">{copy.preferences}</button>
          <button
            disabled={isSaving || referenceOperationBusy}
            onClick={requestNativeClose}
            type="button"
          >
            {copy.close}
          </button>
        </div>
      </header>
      <section aria-label={copy.workspaceControls} className="toolbar">
        <div className="selectors">
          <label>
            {copy.mode} <select
              onChange={(event) => changeMode(event.target.value as WorkspaceMode)}
              value={preferences.mode}
            >
              <option value="normal">{copy.normalMode}</option>
              <option value="transcription">{copy.transcriptionMode}</option>
            </select>
          </label>
          <label>
            {copy.layout} <select onChange={(event) => changeLayout(event.target.value as LayoutId)} value={layout}>
              {layoutOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
            </select>
          </label>
        </div>
        <div aria-label={copy.focusControls} className="focus-controls">
          {preferences.mode === "transcription" && (
            <button
              aria-pressed={focusPane === "reference"}
              disabled={!documentOpen}
              onClick={() => setFocusPane("reference")}
              title={copy.focusOriginal}
              type="button"
            >
              {copy.focusOriginal}
            </button>
          )}
          <button aria-pressed={focusPane === "editor"} disabled={!documentOpen} onClick={() => setFocusPane("editor")} title={copy.focusEditor} type="button">
            {copy.focusEditor}
          </button>
          <button aria-pressed={focusPane === "preview"} disabled={!documentOpen} onClick={() => setFocusPane("preview")} title={copy.focusPreview} type="button">
            {copy.focusPreview}
          </button>
          {focusPane && <button onClick={() => setFocusPane(null)} title={copy.exitFocus} type="button">{copy.exitFocus}</button>}
        </div>
      </section>
      <section
        aria-label={copy.workspace}
        className={`workspace layout-${layout}${focusPane ? ` focus-${focusPane}` : ""}`}
        style={setSplitStyle}
      >
        {paneOrder.map((pane) => panes[pane])}
        {!focusPane && (layout === "N1" || layout === "T1" || layout === "T2") &&
          <PanelDivider key={`${layout}-x`} layout={layout} axis="x" split={split}
            label={xLabel} onChange={changeSplit} />}
        {!focusPane && (layout === "N2" || layout === "T1" || layout === "T2") &&
          <PanelDivider key={`${layout}-y`} layout={layout} axis="y" split={split}
            label={yLabel} onChange={changeSplit} />}

      </section>
      <LifecycleDialogs lifecycle={lifecycle} referenceAssets={referenceAssets} copy={copy}
        preferences={preferences} setPreferences={setPreferences} fonts={engineCapabilities.fonts} />
      <InformationDialog kind={informationDialog} dialogRef={informationDialogRef} copy={copy}
        checkingUpdate={checkingUpdate} updateResult={updateResult} updateError={updateError}
        browserError={browserError} onClose={() => setInformationDialog(null)} openHelp={openHelp}
        brand={<AppBrand label={copy.projectHome} onOpen={() => {void openHelp("home");}} />} />
    </main>
  );
}
