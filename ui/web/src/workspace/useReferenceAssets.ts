import { useEffect, useRef, useState } from "react";
import type { Dispatch, RefObject, SetStateAction } from "react";
import { MAX_REFERENCE_PAGES } from "../reference/pdf-policy.js";
import { discardReferenceImages, onNativeReferenceDrop, pruneReferenceImages, referenceImageUrl,
  stageReferenceAssets, writeRecoverySnapshot } from "./native-files.js";
import { createRecoverySnapshot } from "./recovery.js";
import {
  applyReferenceImport,
  createReferenceSet,
  orderStagedReferencePages,
  referenceAssetIds,
} from "./reference-set.js";
import type { DialogKind, DocumentSnapshot, PdfImport, PendingReferenceImport, RecoveryDraft,
  StagedReferenceAssets, Status, WorkspaceCopy, WorkspacePreferences } from "./types";

export function useReferenceAssets({ currentDocument, recoverySequence,
  currentRecoveryDraft, copyRef, setStatus, setActiveDialog, setDialogError, setPreferences }: {
  currentDocument: RefObject<DocumentSnapshot>;
  recoverySequence: RefObject<number>;
  currentRecoveryDraft: () => RecoveryDraft | null;
  copyRef: RefObject<WorkspaceCopy>;
  setStatus: Dispatch<SetStateAction<Status>>;
  setActiveDialog: Dispatch<SetStateAction<DialogKind>>;
  setDialogError: Dispatch<SetStateAction<string>>;
  setPreferences: Dispatch<SetStateAction<WorkspacePreferences>>;
}) {
  const [references, setReferences] = useState(createReferenceSet);
  const currentReferences = useRef(references);
  currentReferences.current = references;
  const [referenceSources, setReferenceSources] = useState<Record<string, string>>({});
  const currentReferenceSources = useRef(referenceSources);
  currentReferenceSources.current = referenceSources;
  const [pendingReferenceImport, setPendingReferenceImport] = useState<PendingReferenceImport | null>(null);
  const pendingReferenceImportRef = useRef<PendingReferenceImport | null>(null);
  const [isImportingReferences, setIsImportingReferences] = useState(false);
  const importingReferences = useRef(false);
  const referenceCommitInFlight = useRef(false);
  const [isCommittingReferences, setIsCommittingReferences] = useState(false);
  const [isHandlingReferenceChoice, setIsHandlingReferenceChoice] = useState(false);
  const handlingReferenceChoice = useRef(false);

  async function closeReferencePdfs(ids: string[], sources: Record<string, string>) {
    const urls = ids.flatMap((id) => sources[id] ? [sources[id]] : []);
    if (urls.length === 0) return;
    let closePdfDocument: typeof import("../reference/pdf-runtime").closePdfDocument;
    try {
      closePdfDocument = (await import("../reference/pdf-runtime")).closePdfDocument;
    } catch (error) {
      setStatus({ kind: "error", message: error instanceof Error ? error.message : String(error) });
      return;
    }
    await Promise.all(urls.map(async (source) => {
      try {
        await closePdfDocument(source);
      } catch (error) {
        setStatus({ kind: "error", message: error instanceof Error ? error.message : String(error) });
      }
    }));
  }

  async function discardStagedReferenceAssets(
    assetIds: string[],
    pdfIds: string[],
    sources: Record<string, string>,
  ) {
    await closeReferencePdfs(pdfIds, sources);
    try {
      await discardReferenceImages(assetIds);
    } catch (error) {
      setStatus({ kind: "error", message: error instanceof Error ? error.message : String(error) });
    }
  }

  async function commitReferenceSet(
    next: ReturnType<typeof createReferenceSet>,
    sources: Record<string, string>,
  ) {
    if (referenceCommitInFlight.current) throw new Error(copyRef.current.imageImportInProgress);
    referenceCommitInFlight.current = true;
    setIsCommittingReferences(true);
    const previous = currentReferences.current;
    const previousSources = currentReferenceSources.current;
    const retainedPdfIds = new Set(next.pdfs.map(({ id }) => id));
    const removedPdfIds = previous.pdfs
      .filter(({ id }) => !retainedPdfIds.has(id))
      .map(({ id }) => id);
    currentReferences.current = next;
    try {
      const sequence = ++recoverySequence.current;
      const snapshot = createRecoverySnapshot(
        currentDocument.current,
        currentRecoveryDraft(),
        next,
      );
      if (!(await writeRecoverySnapshot(sequence, snapshot))) {
        throw new Error(copyRef.current.recoveryFailed);
      }
      setReferences(next);
      const retainedSources = Object.fromEntries(
        referenceAssetIds(next).flatMap((id) => sources[id] ? [[id, sources[id]]] : []),
      );
      currentReferenceSources.current = retainedSources;
      setReferenceSources(retainedSources);
      await closeReferencePdfs(removedPdfIds, previousSources);
      try {
        await pruneReferenceImages(referenceAssetIds(next));
      } catch (error) {
        setStatus({ kind: "error", message: error instanceof Error ? error.message : String(error) });
      }
    } catch (error) {
      currentReferences.current = previous;
      throw error;
    } finally {
      referenceCommitInFlight.current = false;
      setIsCommittingReferences(false);
    }
  }

  async function importReferences(paths: string[] | null = null) {
    if (importingReferences.current || pendingReferenceImportRef.current || referenceCommitInFlight.current) {
      setStatus({ kind: "error", message: copyRef.current.imageImportInProgress });
      return;
    }
    if (paths && paths.length > 1) {
      setStatus({ kind: "error", message: copyRef.current.singleReferenceFile });
      return;
    }
    importingReferences.current = true;
    setIsImportingReferences(true);
    let staged: StagedReferenceAssets | null = null;
    const sources: Record<string, string> = {};
    let stagedOwnedByPrompt = false;
    let committed = false;
    try {
      try {
        staged = await stageReferenceAssets(
          paths,
          currentDocument.current.suggestedPath ?? currentDocument.current.path,
        );
      } catch (error) {
        setStatus({
          kind: "error",
          message: `${copyRef.current.imageImportFailed} ${error instanceof Error ? error.message : String(error)}`,
        });
        return;
      }
      if (!staged || staged.order.length === 0) return;
      if (staged.order.length > 1) {
        setStatus({ kind: "error", message: copyRef.current.singleReferenceFile });
        return;
      }
      for (const image of staged.images) {
        const source = referenceImageUrl(image.path);
        const probe = new Image();
        probe.src = source;
        try {
          await probe.decode();
        } finally {
          probe.src = "";
        }
        sources[image.id] = source;
      }

      const parsedPdfs: PdfImport[] = [];
      let importedPageCount = staged.images.length;
      let inspectPdf: typeof import("../reference/pdf-runtime").inspectPdfDocument | null = null;
      if (staged.pdfs.length > 0) {
        inspectPdf = (await import("../reference/pdf-runtime")).inspectPdfDocument;
      }
      for (const pdf of staged.pdfs) {
        if (!inspectPdf) throw new Error("PDF parser is unavailable");
        const source = referenceImageUrl(pdf.path);
        sources[pdf.id] = source;
        const inspected = await inspectPdf(
          source,
          pdf,
          MAX_REFERENCE_PAGES - importedPageCount,
        );
        importedPageCount += inspected.pages.length;
        parsedPdfs.push(inspected);
      }
      const ordered = orderStagedReferencePages(staged.order, staged.images, parsedPdfs);
      const imported = applyReferenceImport(
        createReferenceSet(),
        ordered.pages,
        "replace",
        ordered.pdfs,
      );

      const batch = {
        pages: imported.images,
        pdfs: imported.pdfs,
        sources,
        assetIds: staged.order,
      };
      if (currentReferences.current.images.length > 0) {
        pendingReferenceImportRef.current = batch;
        setPendingReferenceImport(batch);
        setDialogError("");
        setActiveDialog("reference-import");
        stagedOwnedByPrompt = true;
        return;
      }
      const next = applyReferenceImport(
        currentReferences.current,
        batch.pages,
        "replace",
        batch.pdfs,
      );
      await commitReferenceSet(next, sources);
      committed = true;
      setPreferences((current) => ({ ...current, mode: "transcription" }));
    } catch (error) {
      setStatus({
        kind: "error",
        message: `${copyRef.current.imageImportFailed} ${error instanceof Error ? error.message : String(error)}`,
      });
    } finally {
      if (staged && !stagedOwnedByPrompt && !committed) {
        await discardStagedReferenceAssets(
          staged.order,
          staged.pdfs.map(({ id }) => id),
          sources,
        );
      }
      importingReferences.current = false;
      setIsImportingReferences(false);
    }
  }

  async function chooseReferenceImport(choice: "replace" | "cancel") {
    if (handlingReferenceChoice.current) return;
    const pending = pendingReferenceImportRef.current;
    if (!pending) return;
    handlingReferenceChoice.current = true;
    setIsHandlingReferenceChoice(true);
    try {
      if (choice === "cancel") {
        pendingReferenceImportRef.current = null;
        setPendingReferenceImport(null);
        setActiveDialog(null);
        setDialogError("");
        await discardStagedReferenceAssets(
          pending.assetIds,
          pending.pdfs.map(({ id }) => id),
          pending.sources,
        );
        return;
      }
      const next = applyReferenceImport(currentReferences.current, pending.pages, "replace", pending.pdfs);
      await commitReferenceSet(next, pending.sources);
      pendingReferenceImportRef.current = null;
      setPendingReferenceImport(null);
      setActiveDialog(null);
      setDialogError("");
      setPreferences((current) => ({ ...current, mode: "transcription" }));
    } catch (error) {
      setDialogError(error instanceof Error ? error.message : String(error));
    } finally {
      handlingReferenceChoice.current = false;
      setIsHandlingReferenceChoice(false);
    }
  }

  function updateReferences(next: ReturnType<typeof createReferenceSet>) {
    currentReferences.current = next;
    setReferences(next);
  }

  useEffect(() => {
    let cancelled = false;
    let unlisten: (() => void) | undefined;
    void onNativeReferenceDrop((paths) => {
      const references = paths.filter((path) => /\.(png|jpe?g|pdf)$/i.test(path));
      if (references.length) void importReferences(references);
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

  async function discardPendingImport() {
    const pending = pendingReferenceImportRef.current;
    if (!pending) return;
    pendingReferenceImportRef.current = null;
    setPendingReferenceImport(null);
    await discardStagedReferenceAssets(pending.assetIds, pending.pdfs.map(({ id }) => id), pending.sources);
  }

  function restoreReferences(next: ReturnType<typeof createReferenceSet>, sources: Record<string, string>) {
    updateReferences(next);
    currentReferenceSources.current = sources;
    setReferenceSources(sources);
    pendingReferenceImportRef.current = null;
    setPendingReferenceImport(null);
  }

  return { references, referenceSources, currentReferences, pendingReferenceImport,
    isImportingReferences, isCommittingReferences, isHandlingReferenceChoice,
    commitReferenceSet, importReferences, chooseReferenceImport, updateReferences,
    discardPendingImport, restoreReferences,
    isImporting: () => importingReferences.current,
    isChoosingImport: () => handlingReferenceChoice.current,
    isCommitting: () => referenceCommitInFlight.current };
}
