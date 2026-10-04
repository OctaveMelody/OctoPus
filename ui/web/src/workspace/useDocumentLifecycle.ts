import { useEffect, useRef, useState } from "react";
import type { Dispatch, RefObject, SetStateAction } from "react";
import type { JpsEditorHandle } from "../editor/JpsEditor";
import type { useReferenceAssets } from "./useReferenceAssets";
import type { useScorePreview } from "./useScorePreview";
import type { TranscriptionContext } from "./useTranscriptionSession";
import type { WorkspaceCopy, WorkspacePreferences, FocusPane, LifecycleAction, DialogKind,
  CatalogDocument, NewScoreFields, CodecResponse, LoadedJps, SerializedJps, RecoveryDraft,
  RecoverySnapshot, DocumentSnapshot, Status } from "./types";
import { beginDocumentSave, createDocumentSession, finishDocumentSave, isDocumentDirty } from "./document.js";
import { createNewScore, createNewScorePageConfig, normalizeJpsFileName } from "./new-score.js";
import { destroyNativeWindow, listJpsDocuments, nativeCloseDisposition, openJpsDocument,
  openJpsCatalogDocument, pruneReferenceImages, referenceImageUrl, readRecoverySnapshot,
  resolveReferenceImages, saveJpsDocument, openRecentJpsDocument, writeRecoverySnapshot,
  onNativeCloseRequested } from "./native-files.js";
import { createRecoverySnapshot, parseRecoverySnapshot } from "./recovery.js";
import { createReferenceSet, referenceAssetIds } from "./reference-set.js";
import { rememberRecentFile } from "./recent-files.js";
import { getStorage } from "./workspace-storage.js";

type ReferenceAssets = ReturnType<typeof useReferenceAssets>;
type LifecycleServices = {
  referenceAssets: ReferenceAssets;
  resetPreview: ReturnType<typeof useScorePreview>["resetPreview"];
  bindReview(context: TranscriptionContext): void;
  clearReview(): void;
  isTranscribing(): boolean;
};

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

export function useDocumentLifecycle({ copyRef, setStatus, setPreferences, setFocusPane,
  editorController, getServices: serviceProvider }: {
  copyRef: RefObject<WorkspaceCopy>;
  setStatus: Dispatch<SetStateAction<Status>>;
  setPreferences: Dispatch<SetStateAction<WorkspacePreferences>>;
  setFocusPane: Dispatch<SetStateAction<FocusPane>>;
  editorController: RefObject<JpsEditorHandle | null>;
  getServices: () => LifecycleServices;
}) {
  // Resolve external owners at event/effect time. Reference/transcription hooks depend on
  // the lifecycle-owned document/recovery refs and are initialized later in App's render.
  const services = useRef(serviceProvider);
  services.current = serviceProvider;
  const getServices = () => services.current();
  const copy = copyRef.current;
  const pendingTranscription = useRef<TranscriptionContext | null>(null);
  const recentPath = useRef<string | null>(null);
  const [score, setScore] = useState(() => createDocumentSession({
    id: crypto.randomUUID(),
    name: "Untitled.jps",
    source: "Q: 1 2 3 4 |",
  }));
  const [documentOpen, setDocumentOpen] = useState(true);
  const currentDocument = useRef(score);
  currentDocument.current = score;
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
  activeDialogRef.current = activeDialog;
  pendingActionRef.current = pendingAction;
  recoveryReadyRef.current = recoveryReady;
  newScoreDraftRef.current = {
    active: newScoreDraftActive,
    name: newFileName,
    fields: newScoreFields,
    dirty: newScoreDraftActive && newScoreDraftChanged(newFileName, newScoreFields),
  };
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (activeDialog && !dialog.open) dialog.showModal();
    else if (!activeDialog && dialog.open) dialog.close();
  }, [activeDialog]);

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

  function replaceDocument(nextDocument: DocumentSnapshot, notice = "") {
    transitionSequence.current += 1;
    pendingTranscription.current = null;
    currentDocument.current = nextDocument;
    getServices().resetPreview(nextDocument);
    setScore(nextDocument);
    setDocumentOpen(true);
    getServices().clearReview();
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
      getServices().bindReview(pending);
      setStatus({ kind: "transcribed", issues: pending.draft.issues.length });
      setFocusPane(null);
      return;
    }
    if (action === "close-document") {
      try {
        await getServices().referenceAssets.commitReferenceSet(createReferenceSet(), {});
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
      const path = recentPath.current;
      recentPath.current = null;
      const opened = path ? await openRecentJpsDocument(path) : await openJpsDocument(rememberedPath(LAST_OPENED_JPS_PATH_KEY));
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
        setPreferences(current => ({...current, recentFiles: rememberRecentFile(current.recentFiles, opened.path)}));
      }
    } catch (error) {
      if (sequence === transitionSequence.current) {
        setStatus({ kind: "error", message: error instanceof Error ? error.message : String(error) });
      }
    }
  }

  function requestAction(action: LifecycleAction, recentFilePath: string | null = null) {
    recentPath.current = action === "open" ? recentFilePath : null;
    if (saving.current || isSaving || getServices().referenceAssets.isCommitting()) return;
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
    recentPath.current = null;
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
          getServices().referenceAssets.currentReferences.current,
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
      setPreferences(current => ({...current, recentFiles: rememberRecentFile(current.recentFiles, savedPath)}));
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
        createRecoverySnapshot(finished, currentRecoveryDraft(), getServices().referenceAssets.currentReferences.current),
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
      await getServices().referenceAssets.discardPendingImport();
      if (!recoveryPersisted) {
        const sequence = ++recoverySequence.current;
        if (!(await writeRecoverySnapshot(sequence, recoveryText))) {
          throw new Error(copyRef.current.recoverySaveSuperseded);
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
      getServices().referenceAssets.isImporting()
      || getServices().referenceAssets.isChoosingImport()
      || getServices().referenceAssets.isCommitting()
      || getServices().isTranscribing()
    ) {
      setStatus({ kind: "error", message: getServices().isTranscribing()
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
      getServices().referenceAssets.currentReferences.current,
    ));
  }

  function cancelDirtyAction() {
    recentPath.current = null;
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
                getServices().referenceAssets.currentReferences.current,
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
      getServices().referenceAssets.restoreReferences(recovery.references, sourcePaths);
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

  function prepareTranscription(context: TranscriptionContext) {
    pendingTranscription.current = context;
    setStatus({kind: "ready"});
    requestAction("transcribe-new");
  }

  return {score, setScore, currentDocument, documentOpen, activeDialog, setActiveDialog,
    activeDialogRef, dialogRef, dialogError, setDialogError, newFileName, setNewFileName,
    newScoreFields, setNewScoreFields, newScoreDraftActive, setNewScoreDraftActive,
    settingsDraftRef, settingsDraftReset, examples, examplesLoaded, exampleFilter,
    setExampleFilter, isSaving, saving, recoveryReady, recoveryReadyRef, recoveryInitialized,
    recoverySequence, recoveryCandidate, recoveryError, isRecoveryActionRunning,
    currentRecoveryDraft, requestAction, requestNativeClose, saveDocument, prepareTranscription,
    resolveSettingsDraft, resolveDirtyAction, cancelDirtyAction, cancelSettingsDraftAction,
    createScore, chooseCatalogDocument, restoreRecovery, discardRecovery, continueWithoutRecovery};
}

export type DocumentLifecycle = ReturnType<typeof useDocumentLifecycle>;

export function useRecoveryPersistence(lifecycle: DocumentLifecycle, referenceAssets: ReferenceAssets,
  setStatus: Dispatch<SetStateAction<Status>>) {
  const {score, currentDocument, newScoreDraftActive, newFileName, newScoreFields,
    recoveryInitialized, recoverySequence, currentRecoveryDraft} = lifecycle;
  const {references, currentReferences} = referenceAssets;
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

}
