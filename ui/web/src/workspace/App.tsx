import { useEffect, useRef, useState } from "react";
import type { CSSProperties, ReactNode } from "react";

import { JpsEditor, type JpsEditorHandle } from "../editor/JpsEditor";
import { PageSettings } from "./PageSettings";
import { ReferencePanel } from "../reference/ReferencePanel";
import { messages } from "./i18n";
import type { Language } from "./i18n";
import brandMark from "./octopus.svg";
import { useScorePreview } from "./useScorePreview";
import { ScorePreview } from "./ScorePreview";
import { exportStatusText, useScoreExports } from "./useScoreExports";
import { useReferenceAssets } from "./useReferenceAssets";
import type {
  WorkspacePreferences,
  WorkspaceMode,
  LayoutId,
  PaneId,
  FocusPane,
  LifecycleAction,
  DialogKind,
  CatalogDocument,
  NewScoreFields,
  CodecResponse,
  LoadedJps,
  SerializedJps,
  EngineCapabilities,
  RecoveryDraft,
  RecoverySnapshot,
  DocumentSnapshot,
  TranscriptionIssue,
  TranscriptionDraft,
  Status,
} from "./types";
import {
  beginDocumentSave,
  createDocumentSession,
  finishDocumentSave,
  isCurrentDocumentRevision,
  isDocumentDirty,
  isPageConfigDirty,
  updateDocumentPageConfig,
  updateDocumentSource,
} from "./document.js";
import {
  createNewScore,
  createNewScorePageConfig,
  normalizeJpsFileName,
} from "./new-score.js";
import {
  destroyNativeWindow,
  getEngineCapabilities,
  listJpsDocuments,
  nativeCloseDisposition,
  openJpsDocument,
  openJpsCatalogDocument,
  onNativeCloseRequested,
  pruneReferenceImages,
  referenceImageUrl,
  readRecoverySnapshot,
  resolveReferenceImages,
  saveJpsDocument,
  transcribeReference,
  writeRecoverySnapshot,
} from "./native-files.js";
import {
  createRecoverySnapshot,
  parseRecoverySnapshot,
} from "./recovery.js";
import {
  createReferenceSet,
  referenceAssetIds,
  selectReferenceImage,
  updateReferenceView,
} from "./reference-set.js";
import { defaultPreferences, readPreferences, writePreferences } from "./preferences.js";

const EMPTY_NEW_SCORE: NewScoreFields = {
  title: "",
  subtitle: "",
  lyricist: "",
  composer: "",
  otherAuthors: "",
  keyNote: "C",
  keyAccidental: "",
  beatNumerator: 4,
  beatDenominator: 4,
  tempo: "",
};

function getStorage(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

const LAST_OPENED_JPS_PATH_KEY = "octopus.last-opened-jps-path.v1";
const LAST_SAVED_JPS_PATH_KEY = "octopus.last-saved-jps-path.v1";

function rememberedPath(key: string): string | null {
  try {
    return getStorage()?.getItem(key) || null;
  } catch {
    return null;
  }
}

function rememberPath(key: string, path: string): void {
  try {
    getStorage()?.setItem(key, path);
  } catch {
    // Dialog defaults are a convenience; storage failures must not block files.
  }
}

function newScoreDraftChanged(name: string, fields: NewScoreFields) {
  return name !== "Untitled.jps" || JSON.stringify(fields) !== JSON.stringify(EMPTY_NEW_SCORE);
}

function AppBrand() {
  return (
    <span className="app-brand">
      <img alt="" className="brand-mark" height="40" src={brandMark} width="40" />
      <span className="brand-type">
        <span className="brand-name">Octo<span>Pus</span></span>
        <span className="brand-studio">by <strong>OctaveMelody</strong></span>
      </span>
    </span>
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
  const [score, setScore] = useState(() => createDocumentSession({
    id: crypto.randomUUID(),
    name: "Untitled.jps",
    source: "Q: 1 2 3 4 |",
  }));
  const [documentOpen, setDocumentOpen] = useState(true);
  const [editorHistory, setEditorHistory] = useState({ undo: false, redo: false });
  const [engineCapabilities, setEngineCapabilities] = useState<EngineCapabilities>({
    ocr: false,
    lilypond: false,
  });
  const [isTranscribing, setIsTranscribing] = useState(false);
  const [transcriptionIssues, setTranscriptionIssues] = useState<TranscriptionIssue[]>([]);
  const transcribing = useRef(false);
  const pendingTranscription = useRef<{ draft: TranscriptionDraft; name: string } | null>(null);
  const currentDocument = useRef(score);
  const editorController = useRef<JpsEditorHandle | null>(null);
  currentDocument.current = score;
  const [status, setStatus] = useState<Status>({ kind: "ready" });
  const [informationDialog, setInformationDialog] = useState<"help" | "about" | null>(null);
  const [activeDialog, setActiveDialog] = useState<DialogKind>(null);
  const [pendingAction, setPendingAction] = useState<LifecycleAction | null>(null);
  const [dialogError, setDialogError] = useState("");
  const [newFileName, setNewFileName] = useState("Untitled.jps");
  const [newScoreFields, setNewScoreFields] = useState(EMPTY_NEW_SCORE);
  const [newScoreDraftActive, setNewScoreDraftActive] = useState(false);
  const [settingsDraftReset, setSettingsDraftReset] = useState(0);
  const [examples, setExamples] = useState<CatalogDocument[]>([]);
  const [examplesLoaded, setExamplesLoaded] = useState(false);
  const [exampleFilter, setExampleFilter] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const dialogRef = useRef<HTMLDialogElement>(null);
  const exportMenuRef = useRef<HTMLDetailsElement>(null);
  const helpMenuRef = useRef<HTMLDetailsElement>(null);
  const findMenuRef = useRef<HTMLDetailsElement>(null);
  const transcriptionMenuRef = useRef<HTMLDetailsElement>(null);
  const transitionSequence = useRef(0);
  const saving = useRef(false);
  const [recoveryReady, setRecoveryReady] = useState(false);
  const [recoveryInitialized, setRecoveryInitialized] = useState(false);
  const [recoveryCandidate, setRecoveryCandidate] = useState<RecoverySnapshot | null>(null);
  const [recoveryError, setRecoveryError] = useState("");
  const [isRecoveryActionRunning, setIsRecoveryActionRunning] = useState(false);
  const recoveryActionRunning = useRef(false);
  const recoveryReadyRef = useRef(false);
  const recoverySequence = useRef(0);
  const deferredNativeClose = useRef(false);
  const closeRequestPending = useRef(false);
  const activeDialogRef = useRef<DialogKind>(null);
  const pendingActionRef = useRef<LifecycleAction | null>(null);
  const resumeDialogAfterExit = useRef<{ dialog: DialogKind; action: LifecycleAction | null } | null>(null);
  const informationDialogRef = useRef<HTMLDialogElement>(null);
  const appShortcutRef = useRef<(event: KeyboardEvent) => void>(() => {});
  const newScoreDraftRef = useRef({
    active: false,
    name: "Untitled.jps",
    fields: EMPTY_NEW_SCORE,
    dirty: false,
  });
  const settingsDraftRef = useRef<{
    dirty: boolean;
    config: Record<string, unknown> | null;
  }>({ dirty: false, config: null });
  const copy = messages[preferences.language];
  const copyRef = useRef(copy);
  copyRef.current = copy;
  activeDialogRef.current = activeDialog;
  pendingActionRef.current = pendingAction;
  recoveryReadyRef.current = recoveryReady;
  newScoreDraftRef.current = {
    active: newScoreDraftActive,
    name: newFileName,
    fields: newScoreFields,
    dirty: newScoreDraftActive && newScoreDraftChanged(newFileName, newScoreFields),
  };
  const { isExporting, currentExportStatus, startExport } = useScoreExports({
    score, currentDocument, documentOpen, copyRef });
  const referenceAssets = useReferenceAssets({ currentDocument, recoverySequence,
    currentRecoveryDraft, copyRef, setStatus, setActiveDialog, setDialogError, setPreferences });
  const { references, referenceSources, currentReferences, pendingReferenceImport,
    isImportingReferences, isCommittingReferences, isHandlingReferenceChoice,
    commitReferenceSet, importReferences, chooseReferenceImport, updateReferences } = referenceAssets;

  const preview = useScorePreview({ score, currentDocument, documentOpen, recoveryReady, copy,
    setStatus, editorController, focusPane, setFocusPane });
  const { handleEditorCursor, resetPreview, sourceChanged } = preview;

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
      for (const menu of [exportMenuRef.current, helpMenuRef.current,
        transcriptionMenuRef.current, findMenuRef.current]) {
        if (menu?.open && !menu.contains(event.target)) menu.open = false;
      }
    };
    document.addEventListener("click", closeMenusOnOutsideClick);
    return () => document.removeEventListener("click", closeMenusOnOutsideClick);
  }, []);

  async function requestTranscription(mode: "new" | "append") {
    if (transcribing.current || saving.current || referenceAssets.isImporting()
      || (mode === "append" && !documentOpen)) return;
    const reference = currentReferences.current;
    const selected = reference.images.find((page) => page.id === reference.selectedId);
    if (!selected) return;
    const assetId = selected.kind === "pdf-page" ? selected.pdfId : selected.id;
    const sourceName = selected.kind === "pdf-page"
      ? reference.pdfs.find((pdf) => pdf.id === selected.pdfId)?.name ?? selected.name
      : selected.name;
    const document = currentDocument.current;
    transcribing.current = true;
    setIsTranscribing(true);
    setStatus({ kind: "transcribing" });
    if (transcriptionMenuRef.current) transcriptionMenuRef.current.open = false;
    try {
      const response = await transcribeReference(assetId, document.id, document.revision);
      const draft = response.result;
      if (response.status !== "ok" || !draft || typeof draft.jps !== "string"
        || !Array.isArray(draft.issues)) {
        throw new Error(response.error?.message ?? copy.transcriptionFailed);
      }
      if (!isCurrentDocumentRevision(currentDocument.current, {
        documentId: document.id,
        revision: document.revision,
      })) {
        throw new Error(copy.transcriptionDocumentChanged);
      }
      if (mode === "new") {
        let name = "Untitled.jps";
        try {
          name = normalizeJpsFileName(sourceName.replace(/\.(png|jpe?g|pdf)$/i, ""));
        } catch {
          // A valid reference name can exceed the JPS filename byte limit.
        }
        pendingTranscription.current = { draft, name };
        setStatus({ kind: "ready" });
        requestAction("transcribe-new");
      } else {
        const editor = editorController.current;
        if (!editor) throw new Error(copy.transcriptionEditorUnavailable);
        const existing = document.source;
        const musicStart = draft.jps.search(/^Q\d*(?:\[[^\]\r\n]*\]|"[^"\r\n]*")?:/m);
        if (musicStart < 0) throw new Error(copy.transcriptionNoMusic);
        const body = "\n" + draft.jps.slice(musicStart).trimEnd();
        const prefix = !existing.trim()
          ? ""
          : /\[fenye\]\s*$/.test(existing)
            ? "\n"
            : existing.endsWith("\n") ? "\n[fenye]\n" : "\n\n[fenye]\n";
        editor.appendSource(prefix + (existing.trim() ? body : draft.jps.trimEnd()) + "\n");
        setTranscriptionIssues(draft.issues);
        setStatus({ kind: "transcribed", issues: draft.issues.length });
        setFocusPane(null);
      }
    } catch (error) {
      setStatus({ kind: "error", message: error instanceof Error ? error.message : String(error) });
    } finally {
      transcribing.current = false;
      setIsTranscribing(false);
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
          && typeof capabilities.lilypond === "boolean"
        ) {
          setEngineCapabilities(capabilities);
        }
      })
      .catch(() => {});
    return () => { active = false; };
  }, []);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (activeDialog && !dialog.open) dialog.showModal();
    else if (!activeDialog && dialog.open) dialog.close();
  }, [activeDialog]);

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
    let cancelled = false;
    if (!window.__TAURI__) {
      setRecoveryReady(true);
      setRecoveryInitialized(true);
      return;
    }
    void (async () => {
      try {
        const text = await readRecoverySnapshot();
        if (cancelled) return;
        if (text === null) {
          try {
            await pruneReferenceImages([]);
          } catch (error) {
            setStatus({ kind: "error", message: error instanceof Error ? error.message : String(error) });
          }
          setRecoveryReady(true);
          setRecoveryInitialized(true);
          return;
        }
        let candidate: RecoverySnapshot;
        try {
          candidate = parseRecoverySnapshot(text);
        } catch (error) {
          setRecoveryError(error instanceof Error ? error.message : String(error));
          setActiveDialog("recovery");
          setRecoveryReady(true);
          return;
        }
        try {
          await pruneReferenceImages(referenceAssetIds(candidate.references));
        } catch (error) {
          setStatus({ kind: "error", message: error instanceof Error ? error.message : String(error) });
        }
        if (cancelled) return;
        setRecoveryCandidate(candidate);
        setActiveDialog("recovery");
        setRecoveryReady(true);
      } catch (error) {
        if (cancelled) return;
        setRecoveryError(error instanceof Error ? error.message : String(error));
        setActiveDialog("recovery");
        setRecoveryReady(true);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!recoveryInitialized || !window.__TAURI__) return;
    let timer = 0;
    const persist = () => {
      if (referenceAssets.isCommitting()) {
        timer = window.setTimeout(persist, 50);
        return;
      }
      let text: string | null;
      try {
        text = createRecoverySnapshot(
          currentDocument.current,
          currentRecoveryDraft(),
          currentReferences.current,
        );
      } catch (error) {
        setStatus({ kind: "error", message: error instanceof Error ? error.message : String(error) });
        return;
      }
      const sequence = ++recoverySequence.current;
      void writeRecoverySnapshot(sequence, text).catch((error: unknown) => {
        if (sequence === recoverySequence.current) {
          setStatus({ kind: "error", message: error instanceof Error ? error.message : String(error) });
        }
      });
    };
    timer = window.setTimeout(persist, 250);
    return () => window.clearTimeout(timer);
  }, [score, references, newScoreDraftActive, newFileName, newScoreFields, recoveryInitialized]);

  useEffect(() => {
    let cancelled = false;
    let unlisten: (() => void) | undefined;
    void onNativeCloseRequested((event) => {
      event.preventDefault();
      requestNativeClose();
    }).then((removeListener) => {
      if (cancelled) removeListener();
      else unlisten = removeListener;
    }).catch((error: unknown) => {
      setStatus({ kind: "error", message: error instanceof Error ? error.message : String(error) });
    });
    return () => {
      cancelled = true;
      unlisten?.();
    };
  }, []);

  useEffect(() => {
    if (!recoveryReady || !deferredNativeClose.current) return;
    deferredNativeClose.current = false;
    requestNativeClose();
  }, [activeDialog, recoveryReady]);

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

  function changeSplit(axis: "x" | "y", rawValue: string) {
    const value = Number(rawValue);
    setPreferences((current) => {
      const activeLayout = current.mode === "normal"
        ? current.normalLayout
        : current.transcriptionLayout;
      const currentSplit = current.splits[activeLayout];
      const nextSplit = { ...currentSplit };
      if (activeLayout === "T1") {
        const other = axis === "x" ? currentSplit.y : currentSplit.x;
        nextSplit[axis] = Math.min(60, 80 - other, Math.max(20, value));
      } else {
        const maximum = activeLayout === "N1" || activeLayout === "T2" ? 60 : 80;
        nextSplit[axis] = Math.min(maximum, Math.max(20, value));
      }
      return { ...current, splits: { ...current.splits, [activeLayout]: nextSplit } };
    });
  }

  function replaceDocument(nextDocument: DocumentSnapshot, notice = "") {
    transitionSequence.current += 1;
    pendingTranscription.current = null;
    currentDocument.current = nextDocument;
    resetPreview(nextDocument);
    setScore(nextDocument);
    setDocumentOpen(true);
    setTranscriptionIssues([]);
    setStatus(notice ? { kind: "notice" } : { kind: "ready" });
  }

  async function loadJpsText(
    name: string,
    path: string | null,
    suggestedPath: string | null,
    text: string,
    sequence: number,
  ) {
    const tauri = window.__TAURI__;
    if (!tauri) throw new Error(copy.needsDesktop);
    const id = crypto.randomUUID();
    const response = await tauri.core.invoke<CodecResponse<LoadedJps>>("load_document", {
      args: { documentId: id, documentRevision: 0, name, text },
    });
    if (sequence !== transitionSequence.current) return false;
    const loaded = response.result?.document;
    if (response.status !== "ok" || !loaded) {
      throw new Error(response.error?.message ?? copy.openFailed);
    }
    const nextDocument = createDocumentSession({
      id,
      name: loaded.name,
      path,
      suggestedPath,
      source: loaded.code,
      savedSource: loaded.code,
      savedFileText: text,
      wrapperFields: loaded.wrapper_fields,
      customCode: loaded.custom_code,
      pageConfig: loaded.page_config,
      savedPageConfig: loaded.page_config,
      jsonWrapped: loaded.json_wrapped,
    });
    replaceDocument(nextDocument, loaded.encoding_repaired ? copy.encodingRepaired : "");
    return true;
  }

  async function performAction(action: LifecycleAction) {
    const sequence = ++transitionSequence.current;
    setDialogError("");
    if (action === "new") {
      setNewFileName("Untitled.jps");
      setNewScoreFields(EMPTY_NEW_SCORE);
      setNewScoreDraftActive(true);
      setActiveDialog("new");
      return;
    }
    if (action === "transcribe-new") {
      const pending = pendingTranscription.current;
      pendingTranscription.current = null;
      if (!pending) return;
      replaceDocument(createDocumentSession({
        id: crypto.randomUUID(),
        name: pending.name,
        source: pending.draft.jps,
        savedSource: "",
        pageConfig: createNewScorePageConfig(),
      }));
      setTranscriptionIssues(pending.draft.issues);
      setStatus({ kind: "transcribed", issues: pending.draft.issues.length });
      setFocusPane(null);
      return;
    }
    if (action === "close-document") {
      try {
        await commitReferenceSet(createReferenceSet(), {});
      } catch (error) {
        setStatus({ kind: "error", message: error instanceof Error ? error.message : String(error) });
        return;
      }
      replaceDocument(createDocumentSession({
        id: crypto.randomUUID(),
        name: "Untitled.jps",
        source: "",
        savedSource: "",
      }));
      setDocumentOpen(false);
      setFocusPane(null);
      setNewScoreDraftActive(false);
      return;
    }
    if (action === "examples") {
      setExamples([]);
      setExamplesLoaded(false);
      setExampleFilter("");
      setActiveDialog("examples");
      try {
        const documents = await listJpsDocuments();
        if (sequence === transitionSequence.current) {
          setExamples(documents);
          setExamplesLoaded(true);
        }
      } catch (error) {
        if (sequence === transitionSequence.current) {
          setExamplesLoaded(true);
          setDialogError(error instanceof Error ? error.message : String(error));
        }
      }
      return;
    }
    try {
      const opened = await openJpsDocument(rememberedPath(LAST_OPENED_JPS_PATH_KEY));
      if (!opened || sequence !== transitionSequence.current) return;
      const loaded = await loadJpsText(
        opened.name,
        opened.path,
        opened.suggestedPath,
        opened.text,
        sequence,
      );
      if (loaded) {
        rememberPath(LAST_OPENED_JPS_PATH_KEY, opened.suggestedPath || opened.path);
      }
    } catch (error) {
      if (sequence === transitionSequence.current) {
        setStatus({ kind: "error", message: error instanceof Error ? error.message : String(error) });
      }
    }
  }

  function requestAction(action: LifecycleAction) {
    if (saving.current || isSaving || referenceAssets.isCommitting()) return;
    if (action !== "transcribe-new") pendingTranscription.current = null;
    if (action === "close-document" && !documentOpen) return;
    if (settingsDraftRef.current.dirty) {
      setPendingAction(action);
      setDialogError("");
      setActiveDialog("settings-dirty");
      return;
    }
    if (isDocumentDirty(currentDocument.current)) {
      setPendingAction(action);
      setDialogError("");
      setActiveDialog("dirty");
      return;
    }
    void performAction(action);
  }

  function cancelSettingsDraftAction() {
    const action = pendingActionRef.current;
    if (action === "transcribe-new") pendingTranscription.current = null;
    setDialogError("");
    if (action === "exit") {
      const resume = resumeDialogAfterExit.current;
      resumeDialogAfterExit.current = null;
      closeRequestPending.current = false;
      setPendingAction(resume?.action ?? null);
      setActiveDialog(resume?.dialog ?? null);
    } else {
      setPendingAction(null);
      setActiveDialog(null);
    }
  }

  function resolveSettingsDraft(choice: "apply" | "discard" | "cancel") {
    if (choice === "cancel") {
      cancelSettingsDraftAction();
      return;
    }
    const action = pendingActionRef.current;
    if (!action) return;
    if (choice === "apply" && settingsDraftRef.current.config) {
      editorController.current?.applyPageConfig(settingsDraftRef.current.config);
    } else if (choice === "discard") {
      setSettingsDraftReset((current) => current + 1);
    }
    settingsDraftRef.current = { dirty: false, config: null };
    setDialogError("");
    setPendingAction(null);
    setActiveDialog(null);

    if (action === "exit") {
      if (isDocumentDirty(currentDocument.current) || newScoreDraftRef.current.dirty) {
        setPendingAction("exit");
        setActiveDialog("dirty");
      } else {
        resumeDialogAfterExit.current = null;
        void finishNativeClose(() => createRecoverySnapshot(
          currentDocument.current,
          currentRecoveryDraft(),
          currentReferences.current,
        ));
      }
      return;
    }
    if (isDocumentDirty(currentDocument.current)) {
      setPendingAction(action);
      setActiveDialog("dirty");
    } else {
      void performAction(action);
    }
  }

  async function saveDocument(saveAs = false): Promise<boolean> {
    if (!documentOpen) return false;
    if (saving.current) return false;
    saving.current = true;
    setIsSaving(true);
    const original = currentDocument.current;
    const begun = beginDocumentSave(original, { name: original.name, path: original.path });
    currentDocument.current = begun.document;
    setScore(begun.document);
    try {
      const tauri = window.__TAURI__;
      if (!tauri) throw new Error(copy.needsDesktop);
      const serialized = await tauri.core.invoke<CodecResponse<SerializedJps>>(
        "serialize_document",
        {
          args: {
            documentId: begun.snapshot.documentId,
            documentRevision: begun.snapshot.revision,
            name: begun.snapshot.name,
            code: begun.snapshot.source,
            wrapperFields: begun.snapshot.wrapperFields,
            pageConfig: begun.snapshot.pageConfig,
            pageConfigChanged: begun.snapshot.pageConfigChanged,
            jsonWrapped: begun.snapshot.jsonWrapped,
          },
        },
      );
      if (serialized.status !== "ok" || typeof serialized.result?.text !== "string") {
        throw new Error(serialized.error?.message ?? copy.saveFailed);
      }
      const fileText = serialized.result.text;
      const isSaveAs = saveAs || original.path === null;
      const savedPath = await saveJpsDocument({
        path: original.path,
        suggestedPath: original.suggestedPath ?? original.path,
        suggestedName: original.name,
        recentSavedPath: isSaveAs ? rememberedPath(LAST_SAVED_JPS_PATH_KEY) : null,
        expectedText: original.savedFileText,
        text: fileText,
        saveAs: isSaveAs,
      });
      if (!savedPath || currentDocument.current.id !== original.id) return false;
      rememberPath(LAST_SAVED_JPS_PATH_KEY, savedPath);
      const name = savedPath.split(/[\\/]/).pop() || begun.snapshot.name;
      const snapshot = {
        ...begun.snapshot,
        name,
        path: savedPath,
        suggestedPath: isSaveAs ? savedPath : original.suggestedPath,
      };
      const finished = finishDocumentSave(currentDocument.current, snapshot, fileText);
      currentDocument.current = finished;
      setScore(finished);
      const recoverySequenceNumber = ++recoverySequence.current;
      await writeRecoverySnapshot(
        recoverySequenceNumber,
        createRecoverySnapshot(finished, currentRecoveryDraft(), currentReferences.current),
      );
      const clean = !isDocumentDirty(finished);
      setStatus(clean ? { kind: "saved" } : { kind: "changed" });
      return clean;
    } catch (error) {
      setStatus({ kind: "error", message: error instanceof Error ? error.message : String(error) });
      return false;
    } finally {
      saving.current = false;
      setIsSaving(false);
    }
  }

  function currentRecoveryDraft(): RecoveryDraft | null {
    const draft = newScoreDraftRef.current;
    return draft.active && draft.dirty
      ? { kind: "new", name: draft.name, fields: draft.fields }
      : null;
  }

  async function finishNativeClose(
    recovery: string | null | (() => string | null),
    recoveryPersisted = false,
  ) {
    try {
      const recoveryText = typeof recovery === "function" ? recovery() : recovery;
      await referenceAssets.discardPendingImport();
      if (!recoveryPersisted) {
        const sequence = ++recoverySequence.current;
        if (!(await writeRecoverySnapshot(sequence, recoveryText))) {
          throw new Error("The recovery snapshot was superseded by a newer save.");
        }
      }
      await destroyNativeWindow();
    } catch (error) {
      closeRequestPending.current = false;
      const detail = error instanceof Error ? error.message : String(error);
      setStatus({ kind: "error", message: `${copyRef.current.closeFailed} ${detail}` });
      setDialogError(`${copyRef.current.closeFailed} ${detail}`);
    }
  }

  function requestNativeClose() {
    if (!window.__TAURI__ || closeRequestPending.current) return;
    if (
      referenceAssets.isImporting()
      || referenceAssets.isChoosingImport()
      || referenceAssets.isCommitting()
      || transcribing.current
    ) {
      setStatus({ kind: "error", message: transcribing.current
        ? copyRef.current.transcribing
        : copyRef.current.imageImportInProgress });
      return;
    }
    const disposition = nativeCloseDisposition(
      recoveryReadyRef.current,
      activeDialogRef.current === "recovery",
    );
    if (disposition === "defer") {
      deferredNativeClose.current = true;
      return;
    }
    if (disposition === "preserve") {
      closeRequestPending.current = true;
      void finishNativeClose(null, true);
      return;
    }
    beginNativeCloseRequest();
  }

  function beginNativeCloseRequest() {
    if (closeRequestPending.current) return;
    closeRequestPending.current = true;
    resumeDialogAfterExit.current = {
      dialog: activeDialogRef.current,
      action: pendingActionRef.current,
    };
    if (settingsDraftRef.current.dirty && !saving.current) {
      setPendingAction("exit");
      setDialogError("");
      setActiveDialog("settings-dirty");
      return;
    }
    if (
      saving.current
      || isDocumentDirty(currentDocument.current)
      || newScoreDraftRef.current.dirty
    ) {
      setPendingAction("exit");
      setDialogError("");
      setActiveDialog("dirty");
      return;
    }
    void finishNativeClose(() => createRecoverySnapshot(
      currentDocument.current,
      currentRecoveryDraft(),
      currentReferences.current,
    ));
  }

  function cancelDirtyAction() {
    const action = pendingActionRef.current;
    if (action === "transcribe-new") pendingTranscription.current = null;
    setDialogError("");
    if (action === "exit") {
      const resume = resumeDialogAfterExit.current;
      resumeDialogAfterExit.current = null;
      closeRequestPending.current = false;
      setPendingAction(resume?.action ?? null);
      setActiveDialog(resume?.dialog ?? null);
      return;
    }
    setPendingAction(null);
    setActiveDialog(null);
  }

  async function resolveDirtyAction(choice: "save" | "discard" | "cancel") {
    if (choice === "cancel") {
      cancelDirtyAction();
      return;
    }
    const action = pendingAction;
    if (!action) return;
    if (choice === "save") {
      if (action === "exit") {
        const documentWasDirty = isDocumentDirty(currentDocument.current);
        if (documentWasDirty && !(await saveDocument())) {
          setDialogError(copy.saveBeforeContinue);
          return;
        }
        if (pendingActionRef.current !== "exit") return;
        try {
          if (documentWasDirty) await finishNativeClose(null, true);
          else {
            await finishNativeClose(
              () => createRecoverySnapshot(
                currentDocument.current,
                currentRecoveryDraft(),
                currentReferences.current,
              ),
            );
          }
        } catch (error) {
          setDialogError(error instanceof Error ? error.message : String(error));
        }
        return;
      }
      if (!(await saveDocument())) {
        setDialogError(copy.saveBeforeContinue);
        return;
      }
      if (pendingActionRef.current !== action) return;
    } else if (action === "exit") {
      await finishNativeClose(null);
      return;
    }
    setPendingAction(null);
    setActiveDialog(null);
    await performAction(action);
  }

  function beginRecoveryAction() {
    if (recoveryActionRunning.current) return false;
    recoveryActionRunning.current = true;
    setIsRecoveryActionRunning(true);
    return true;
  }

  function endRecoveryAction() {
    recoveryActionRunning.current = false;
    setIsRecoveryActionRunning(false);
  }

  async function restoreRecovery() {
    const recovery = recoveryCandidate;
    if (!recovery || !beginRecoveryAction()) return;
    try {
      const sourcePaths: Record<string, string> = {};
      try {
        const resolved = await resolveReferenceImages(referenceAssetIds(recovery.references));
        for (const image of resolved) sourcePaths[image.id] = referenceImageUrl(image.path);
      } catch (error) {
        setStatus({ kind: "error", message: error instanceof Error ? error.message : String(error) });
      }
      const recovered = recovery.document;
      replaceDocument(createDocumentSession({
        id: crypto.randomUUID(),
        name: recovered.name,
        source: recovered.source,
        savedSource: recovered.savedSource,
        savedFileText: recovered.savedFileText,
        suggestedPath: recovered.suggestedPath,
        wrapperFields: recovered.wrapperFields,
        customCode: recovered.customCode,
        pageConfig: recovered.pageConfig,
        savedPageConfig: recovered.savedPageConfig,
        jsonWrapped: recovered.jsonWrapped,
        revision: recovered.revision,
      }));
      referenceAssets.restoreReferences(recovery.references, sourcePaths);
      setRecoveryCandidate(null);
      setRecoveryError("");
      if (recovery.draft) {
        setNewFileName(recovery.draft.name);
        setNewScoreFields(recovery.draft.fields);
        setNewScoreDraftActive(true);
        setActiveDialog("new");
      } else {
        setNewScoreDraftActive(false);
        setActiveDialog(null);
      }
      setRecoveryInitialized(true);
    } finally {
      endRecoveryAction();
    }
  }

  async function discardRecovery() {
    if (!beginRecoveryAction()) return;
    try {
      const sequence = ++recoverySequence.current;
      await writeRecoverySnapshot(sequence, null);
      try {
        await pruneReferenceImages([]);
      } catch (error) {
        setStatus({ kind: "error", message: error instanceof Error ? error.message : String(error) });
      }
      setRecoveryCandidate(null);
      setRecoveryError("");
      setRecoveryInitialized(true);
      setActiveDialog(null);
    } catch (error) {
      setRecoveryError(error instanceof Error ? error.message : String(error));
    } finally {
      endRecoveryAction();
    }
  }

  async function continueWithoutRecovery() {
    if (!beginRecoveryAction()) return;
    try {
      try {
        await pruneReferenceImages([]);
      } catch (error) {
        setStatus({ kind: "error", message: error instanceof Error ? error.message : String(error) });
      }
      setRecoveryCandidate(null);
      setRecoveryError("");
      setRecoveryInitialized(true);
      setActiveDialog(null);
    } finally {
      endRecoveryAction();
    }
  }

  async function chooseCatalogDocument(document: CatalogDocument) {
    const sequence = ++transitionSequence.current;
    setActiveDialog(null);
    try {
      const opened = await openJpsCatalogDocument(document.kind, document.name);
      if (sequence !== transitionSequence.current) return;
      await loadJpsText(opened.name, opened.path, opened.suggestedPath, opened.text, sequence);
    } catch (error) {
      if (sequence === transitionSequence.current) {
        setStatus({ kind: "error", message: error instanceof Error ? error.message : String(error) });
      }
    }
  }

  function createScore(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      const name = normalizeJpsFileName(newFileName);
      const source = createNewScore(newScoreFields);
      replaceDocument(createDocumentSession({
        id: crypto.randomUUID(),
        name,
        source,
        savedSource: "",
        pageConfig: createNewScorePageConfig(),
      }));
      setNewScoreDraftActive(false);
      setActiveDialog(null);
    } catch (error) {
      setDialogError(error instanceof Error ? error.message : String(error));
    }
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
    "--split-x": `${split.x}%`,
    "--split-y": `${split.y}%`,
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
  const panes: Record<PaneId, ReactNode> = {
    editor: (
      <section aria-label={copy.source} className="panel editor-panel" key="editor">
        <div className="panel-heading">
          <div className="editor-heading-title">
            <h2>{copy.source}</h2>
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
          <div aria-label={copy.editorTools} className="editor-heading-tools" role="toolbar">
            <button disabled={!documentOpen || !editorHistory.undo} onClick={() => editorController.current?.undo()} type="button">
              {copy.undo}
            </button>
            <button disabled={!documentOpen || !editorHistory.redo} onClick={() => editorController.current?.redo()} type="button">
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
            <details className="find-menu" ref={findMenuRef} onKeyDown={(event) => {
              if (event.key === "Escape") {
                event.currentTarget.open = false;
                event.currentTarget.querySelector("summary")?.focus();
              }
            }}>
              <summary aria-disabled={!documentOpen} onClick={(event) => {
                if (!documentOpen) event.preventDefault();
              }}>{copy.find}</summary>
              <div className="find-menu-items" role="group" aria-label={copy.find}>
                {[false, true].map((replace) => (
                  <button key={String(replace)} disabled={!documentOpen} onClick={() => {
                    if (findMenuRef.current) findMenuRef.current.open = false;
                    editorController.current?.find(replace);
                  }} type="button">{replace ? copy.findReplace : copy.find}</button>
                ))}
              </div>
            </details>
            <button disabled={!documentOpen} onClick={() => editorController.current?.selectAll()} type="button">
              {copy.selectAll}
            </button>
            <button className="heading-action" disabled={!documentOpen} onClick={() => editorController.current?.formatSource()} type="button">
              {copy.formatSource}
            </button>
          </div>
        </div>
        {documentOpen && <JpsEditor
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
                  {copy.transcriptionIssuePage(issue.page)}: {issue.detail}
                  {issue.regions.length > 0 && ` (${issue.regions.map((box) => box.join(", ")).join("; ")})`}
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
        images={referencePanelImages}
        busy={referenceOperationBusy}
        importing={isImportingReferences}
        transcribing={isTranscribing}
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
  const visibleExamples = examples.filter((document) =>
    document.name.toLowerCase().includes(exampleFilter.trim().toLowerCase())
  );

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
    if (key === "e") {
      if (editorController.current?.insertLast()) event.preventDefault();
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
        <h1 aria-label={copy.title} className="topbar-title"><AppBrand /></h1>
        <nav aria-label={copy.documentActions} className="document-actions">
          <button disabled={isSaving || referenceOperationBusy} onClick={() => requestAction("new")} type="button">{copy.new}</button>
          <button disabled={isSaving || referenceOperationBusy} onClick={() => requestAction("open")} type="button">{copy.open}</button>
          <button disabled={!documentOpen || isSaving || referenceOperationBusy} onClick={() => { void saveDocument(); }} type="button">{copy.save}</button>
          <button disabled={!documentOpen || isSaving || referenceOperationBusy} onClick={() => { void saveDocument(true); }} type="button">{copy.saveAs}</button>
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
              <button
                aria-describedby="lilypond-export-help"
                disabled
                type="button"
              >
                {copy.exportLilypond}
              </button>
              <span className="export-menu-note" id="lilypond-export-help">
                {copy.lilypondUnavailable}
              </span>
            </div>
          </details>
          <button disabled={!documentOpen || isSaving || referenceOperationBusy} onClick={() => requestAction("close-document")} type="button">
            {copy.closeDocument}
          </button>
          <details className="help-menu" ref={helpMenuRef}>
            <summary>{copy.helpMenu}</summary>
            <div aria-label={copy.helpMenu} className="help-menu-items">
              <button onClick={(event) => {
                const menu = event.currentTarget.closest("details");
                if (menu) menu.open = false;
                setInformationDialog("help");
              }} type="button">
                {copy.help}
              </button>
              <button onClick={(event) => {
                const menu = event.currentTarget.closest("details");
                if (menu) menu.open = false;
                setInformationDialog("about");
              }} type="button">
                {copy.about}
              </button>
            </div>
          </details>
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
          <label className="workspace-language">
            {copy.language} <select
              onChange={(event) => setPreferences((current) => ({
                ...current,
                language: event.target.value as Language,
              }))}
              value={preferences.language}
            >
              <option value="en">{copy.english}</option>
              <option value="zh-CN">{copy.chinese}</option>
            </select>
          </label>
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
        <div aria-label={copy.layout} className="split-controls">
          {(layout === "N1" || layout === "T1" || layout === "T2") && (
            <label>
              {xLabel} <output>{split.x}%</output>
              <input
                aria-label={xLabel}
                max={layout === "T1" ? Math.min(60, 80 - split.y) : layout === "T2" || layout === "N1" ? 60 : 80}
                min={20}
                onChange={(event) => changeSplit("x", event.target.value)}
                type="range"
                value={split.x}
              />
            </label>
          )}
          {(layout === "N2" || layout === "T1" || layout === "T2") && (
            <label>
              {yLabel}
              <output>{split.y}%</output>
              <input
                aria-label={yLabel}
                max={layout === "T1" ? Math.min(60, 80 - split.x) : 80}
                min={20}
                onChange={(event) => changeSplit("y", event.target.value)}
                type="range"
                value={split.y}
              />
            </label>
          )}
        </div>
        <div aria-label={copy.focusControls} className="focus-controls">
          {preferences.mode === "transcription" && (
            <button
              aria-pressed={focusPane === "reference"}
              disabled={!documentOpen}
              onClick={() => setFocusPane("reference")}
              type="button"
            >
              {copy.focusOriginal}
            </button>
          )}
          <button aria-pressed={focusPane === "editor"} disabled={!documentOpen} onClick={() => setFocusPane("editor")} type="button">
            {copy.focusEditor}
          </button>
          <button aria-pressed={focusPane === "preview"} disabled={!documentOpen} onClick={() => setFocusPane("preview")} type="button">
            {copy.focusPreview}
          </button>
          {focusPane && <button onClick={() => setFocusPane(null)} type="button">{copy.exitFocus}</button>}
          <button onClick={toggleFullscreen} type="button">{copy.fullScreen}</button>
        </div>
      </section>
      <section
        aria-label={copy.workspace}
        className={`workspace layout-${layout}${focusPane ? ` focus-${focusPane}` : ""}`}
        style={setSplitStyle}
      >
        {paneOrder.map((pane) => panes[pane])}
      </section>
      <dialog
        aria-labelledby="lifecycle-dialog-title"
        className="lifecycle-dialog"
        onCancel={(event) => {
          if (referenceAssets.isChoosingImport() || referenceAssets.isCommitting()) {
            event.preventDefault();
            return;
          }
          if (saving.current) {
            event.preventDefault();
            return;
          }
          if (activeDialogRef.current === "recovery") {
            event.preventDefault();
            return;
          }
          event.preventDefault();
          if (activeDialogRef.current === "dirty") {
            cancelDirtyAction();
          } else if (activeDialogRef.current === "settings-dirty") {
            cancelSettingsDraftAction();
          } else if (activeDialogRef.current === "reference-import") {
            void chooseReferenceImport("cancel");
          } else {
            if (activeDialogRef.current === "new") setNewScoreDraftActive(false);
            setActiveDialog(null);
            setDialogError("");
          }
        }}
        ref={dialogRef}
      >
        {activeDialog === "dirty" && (
          <section>
            <h2 id="lifecycle-dialog-title">{copy.unsavedTitle}</h2>
            <p>{copy.unsavedPrompt}</p>
            {dialogError && <p className="dialog-error" role="alert">{dialogError}</p>}
            <div className="dialog-actions">
              <button disabled={isSaving} onClick={() => { void resolveDirtyAction("save"); }} type="button">
                {copy.save}
              </button>
              <button disabled={isSaving} onClick={() => { void resolveDirtyAction("discard"); }} type="button">
                {copy.discard}
              </button>
              <button disabled={isSaving} onClick={() => { void resolveDirtyAction("cancel"); }} type="button">
                {copy.cancel}
              </button>
            </div>
          </section>
        )}
        {activeDialog === "settings-dirty" && (
          <section>
            <h2 id="lifecycle-dialog-title">{copy.settingsDraftTitle}</h2>
            <p>{copy.settingsDraftPrompt}</p>
            {dialogError && <p className="dialog-error" role="alert">{dialogError}</p>}
            <div className="dialog-actions">
              <button className="primary-button" onClick={() => resolveSettingsDraft("apply")} type="button">
                {copy.applySettings}
              </button>
              <button onClick={() => resolveSettingsDraft("discard")} type="button">
                {copy.discardSettingsDraft}
              </button>
              <button onClick={() => resolveSettingsDraft("cancel")} type="button">
                {copy.cancel}
              </button>
            </div>
          </section>
        )}
        {activeDialog === "new" && (
          <form onSubmit={createScore}>
            <h2 id="lifecycle-dialog-title">{copy.newScoreTitle}</h2>
            <div className="new-score-fields">
              <label>{copy.fileName}<input autoFocus onChange={(event) => setNewFileName(event.target.value)} value={newFileName} /></label>
              <label>{copy.scoreTitle}<input required onChange={(event) => setNewScoreFields((current) => ({ ...current, title: event.target.value }))} value={newScoreFields.title} /></label>
              <label>{copy.subtitle}<input onChange={(event) => setNewScoreFields((current) => ({ ...current, subtitle: event.target.value }))} value={newScoreFields.subtitle} /></label>
              <label>{copy.lyricist}<input onChange={(event) => setNewScoreFields((current) => ({ ...current, lyricist: event.target.value }))} value={newScoreFields.lyricist} /></label>
              <label>{copy.composer}<input onChange={(event) => setNewScoreFields((current) => ({ ...current, composer: event.target.value }))} value={newScoreFields.composer} /></label>
              <label>{copy.otherAuthors}<input onChange={(event) => setNewScoreFields((current) => ({ ...current, otherAuthors: event.target.value }))} value={newScoreFields.otherAuthors} /></label>
              <label>{copy.keySignature}<span className="field-pair">
                <select onChange={(event) => setNewScoreFields((current) => ({ ...current, keyNote: event.target.value }))} value={newScoreFields.keyNote}>
                  {"CDEFGAB".split("").map((note) => <option key={note} value={note}>{note}</option>)}
                </select>
                <select aria-label={copy.accidental} onChange={(event) => setNewScoreFields((current) => ({ ...current, keyAccidental: event.target.value as NewScoreFields["keyAccidental"] }))} value={newScoreFields.keyAccidental}>
                  <option value="">{copy.natural}</option><option value="#">{copy.sharp}</option><option value="$">{copy.flat}</option>
                </select>
              </span></label>
              <label>{copy.timeSignature}<span className="field-pair">
                <select aria-label={copy.timeNumerator} onChange={(event) => setNewScoreFields((current) => ({ ...current, beatNumerator: Number(event.target.value) }))} value={newScoreFields.beatNumerator}>
                  {[1, 2, 3, 4, 5, 6, 7, 8, 9].map((value) => <option key={value}>{value}</option>)}
                </select>
                <span aria-hidden="true">/</span>
                <select aria-label={copy.timeDenominator} onChange={(event) => setNewScoreFields((current) => ({ ...current, beatDenominator: Number(event.target.value) }))} value={newScoreFields.beatDenominator}>
                  {[1, 2, 3, 4, 5, 6, 7, 8, 9].map((value) => <option key={value}>{value}</option>)}
                </select>
              </span></label>
              <label>{copy.tempo}<input onChange={(event) => setNewScoreFields((current) => ({ ...current, tempo: event.target.value }))} value={newScoreFields.tempo} /></label>
            </div>
            {dialogError && <p className="dialog-error" role="alert">{dialogError}</p>}
            <div className="dialog-actions">
              <button className="primary-button" type="submit">{copy.create}</button>
              <button onClick={() => {
                setNewScoreDraftActive(false);
                setActiveDialog(null);
                setDialogError("");
              }} type="button">{copy.cancel}</button>
            </div>
          </form>
        )}
        {activeDialog === "examples" && (
          <section>
            <h2 id="lifecycle-dialog-title">{copy.examples}</h2>
            <label className="example-search">{copy.filterExamples}
              <input autoFocus onChange={(event) => setExampleFilter(event.target.value)} type="search" value={exampleFilter} />
            </label>
            {dialogError && <p className="dialog-error" role="alert">{dialogError}</p>}
            <ul className="example-list">
              {visibleExamples.map((document) => (
                <li key={`${document.kind}:${document.name}`}>
                  <button onClick={() => { void chooseCatalogDocument(document); }} type="button">
                    <span>{document.kind === "example" ? copy.example : copy.workingCopy}</span>
                    {" · "}{document.name}
                  </button>
                </li>
              ))}
            </ul>
            {!examplesLoaded && !dialogError && <p>{copy.loadingExamples}</p>}
            {examplesLoaded && examples.length === 0 && !dialogError && <p>{copy.noExamples}</p>}
            {examples.length > 0 && visibleExamples.length === 0 && <p>{copy.noExamples}</p>}
            <div className="dialog-actions">
              <button onClick={() => { setActiveDialog(null); }} type="button">{copy.cancel}</button>
            </div>
          </section>
        )}
        {activeDialog === "reference-import" && pendingReferenceImport && (
          <section>
            <h2 id="lifecycle-dialog-title">{copy.referenceImportChoiceTitle}</h2>
            <p>{copy.referenceImportChoicePrompt(pendingReferenceImport.pages.length)}</p>
            <p>{copy.referenceImageBatch(pendingReferenceImport.pages.length)}</p>
            {dialogError && <p className="dialog-error" role="alert">{dialogError}</p>}
            <div className="dialog-actions">
              <button className="primary-button" disabled={isHandlingReferenceChoice} onClick={() => { void chooseReferenceImport("replace"); }} type="button">
                {copy.replaceReferences}
              </button>
              <button disabled={isHandlingReferenceChoice} onClick={() => { void chooseReferenceImport("cancel"); }} type="button">
                {copy.cancel}
              </button>
            </div>
          </section>
        )}
        {activeDialog === "recovery" && (
          <section>
            <h2 id="lifecycle-dialog-title">{copy.recoveryTitle}</h2>
            <p>{copy.recoveryPrompt}</p>
            {recoveryCandidate && (
              <p>{recoveryCandidate.document.name} · {copy.revision(recoveryCandidate.document.revision)}</p>
            )}
            {recoveryError && <p className="dialog-error" role="alert">{recoveryError}</p>}
            <div className="dialog-actions">
              {recoveryCandidate && (
                <button
                  className="primary-button"
                  disabled={isRecoveryActionRunning}
                  onClick={restoreRecovery}
                  type="button"
                >
                  {copy.restoreRecovery}
                </button>
              )}
              <button
                disabled={isRecoveryActionRunning}
                onClick={() => { void discardRecovery(); }}
                type="button"
              >
                {copy.discardRecovery}
              </button>
              {recoveryError && (
                <button
                  disabled={isRecoveryActionRunning}
                  onClick={continueWithoutRecovery}
                  type="button"
                >
                  {copy.continueWithoutRecovery}
                </button>
              )}
            </div>
          </section>
        )}
      </dialog>
      <dialog
        aria-labelledby="information-dialog-title"
        className="lifecycle-dialog information-dialog"
        onCancel={(event) => {
          event.preventDefault();
          setInformationDialog(null);
        }}
        ref={informationDialogRef}
      >
        {informationDialog === "help" && (
          <section>
            <h2 id="information-dialog-title">{copy.helpTitle}</h2>
            <ul className="help-list">
              <li>{copy.helpEditing}</li>
              <li>{copy.helpMatching}</li>
              <li>{copy.helpShortcuts}</li>
              <li>{copy.helpPageSettings}</li>
            </ul>
            <div className="dialog-actions">
              <button autoFocus className="primary-button" onClick={() => setInformationDialog(null)} type="button">
                {copy.done}
              </button>
            </div>
          </section>
        )}
        {informationDialog === "about" && (
          <section>
            <h2 id="information-dialog-title">{copy.aboutTitle}</h2>
            <AppBrand />
            <p>{copy.aboutDescription}</p>
            <p>{copy.fontCredits}</p>
            <div className="dialog-actions">
              <button autoFocus className="primary-button" onClick={() => setInformationDialog(null)} type="button">
                {copy.done}
              </button>
            </div>
          </section>
        )}
      </dialog>
    </main>
  );
}
