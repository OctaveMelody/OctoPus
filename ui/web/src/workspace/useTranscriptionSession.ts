import {useEffect, useRef, useState} from "react";
import type {RefObject} from "react";
import {isCurrentDocumentRevision} from "./document.js";
import {cancelTranscription as cancelNative, onTranscriptionProgress, transcribeReference} from "./native-files.js";
import {normalizeJpsFileName} from "./new-score.js";
import type {DocumentSnapshot, TranscriptionDraft, WorkspaceCopy} from "./types";

type ReferenceSet = ReturnType<typeof import("./reference-set.js").createReferenceSet>;
export type TranscriptionContext = {pages: string[]; draft: TranscriptionDraft; name: string};
export type TranscriptionProgress = {completed: number; total: number; stage: string};

/** Owns request identity, progress subscription and cancellation. Draft adoption stays guarded. */
export function useTranscriptionSession({currentDocument, getReferences, isBusy, copyRef, onDraft, onError}: {
  currentDocument: RefObject<DocumentSnapshot>;
  getReferences(): ReferenceSet;
  isBusy(mode: "new" | "append"): boolean;
  copyRef: RefObject<WorkspaceCopy>;
  onDraft(mode: "new" | "append", context: TranscriptionContext): void;
  onError(message: string): void;
}) {
  const transcribing = useRef(false);
  const active = useRef<{id: string; document: DocumentSnapshot; cancelled: boolean; cancelling: boolean; started: boolean} | null>(null);
  const [isTranscribing, setIsTranscribing] = useState(false);
  const [isCancelling, setIsCancelling] = useState(false);
  const [progress, setProgress] = useState<TranscriptionProgress | null>(null);
  const callbacks = useRef({isBusy, onDraft, onError});
  callbacks.current = {isBusy, onDraft, onError};
  useEffect(() => () => {
    const job = active.current;
    if (job) {
      job.cancelled = true;
      void cancelNative(job.id, job.document.id, job.document.revision).catch(() => {});
    }
  }, []);

  async function cancelTranscription() {
    const job = active.current;
    if (!job || job.cancelling) return;
    job.cancelling = true;
    job.cancelled = true; // Invalidate draft adoption before sending the native command.
    setIsCancelling(true);
    try {
      await cancelNative(job.id, job.document.id, job.document.revision);
    } catch (error) {
      job.cancelling = false;
      if (active.current === job) {
        setIsCancelling(false);
        callbacks.current.onError(error instanceof Error ? error.message : String(error));
      }
    }
  }

  async function requestTranscription(mode: "new" | "append") {
    if (transcribing.current || callbacks.current.isBusy(mode)) return;
    const reference = getReferences();
    const selected = reference.images.find(page => page.id === reference.selectedId);
    if (!selected) return;
    const assetId = selected.kind === "pdf-page" ? selected.pdfId : selected.id;
    const pages = selected.kind === "pdf-page"
      ? reference.images.filter(page => page.kind === "pdf-page" && page.pdfId === assetId)
        .sort((a, b) => (a.kind === "pdf-page" ? a.pageNumber : 0) - (b.kind === "pdf-page" ? b.pageNumber : 0)).map(page => page.id)
      : [selected.id];
    const sourceName = selected.kind === "pdf-page"
      ? reference.pdfs.find(pdf => pdf.id === assetId)?.name ?? selected.name : selected.name;
    const job = {id: crypto.randomUUID(), document: currentDocument.current, cancelled: false, cancelling: false, started: false};
    active.current = job;
    transcribing.current = true;
    setIsTranscribing(true);
    setIsCancelling(false);
    setProgress(null);
    let unsubscribe = () => {};
    try {
      unsubscribe = await onTranscriptionProgress(payload => {
        const value = payload?.progress;
        if (active.current !== job || job.cancelled || payload.jobId !== job.id
          || payload.documentId !== job.document.id || payload.revision !== job.document.revision
          || !value || !Number.isSafeInteger(value.completed) || !Number.isSafeInteger(value.total)
          || value.total < 1 || value.total > 200 || value.completed < 0 || value.completed > value.total
          || !["recognizing", "compiling"].includes(value.stage)) return;
        setProgress(value);
      });
      if (job.cancelled || active.current !== job) return;
      job.started = true;
      const response = await transcribeReference(assetId, job.document.id, job.document.revision, job.id);
      if (job.cancelled || active.current !== job) return;
      const draft = response.result;
      if (response.status !== "ok" || !draft) throw new Error(response.error?.message ?? copyRef.current.transcriptionFailed);
      if (!isCurrentDocumentRevision(currentDocument.current, {
        documentId: job.document.id, revision: job.document.revision,
      })) throw new Error(copyRef.current.transcriptionDocumentChanged);
      let name = "Untitled.jps";
      try { name = normalizeJpsFileName(sourceName.replace(/\.(png|jpe?g|pdf)$/i, "")); } catch { /* byte cap */ }
      callbacks.current.onDraft(mode, {draft, name, pages});
    } catch (error) {
      if (active.current === job && !job.cancelled) callbacks.current.onError(error instanceof Error ? error.message : String(error));
    } finally {
      unsubscribe();
      if (active.current === job) {
        active.current = null;
        transcribing.current = false;
        setIsTranscribing(false);
        setIsCancelling(false);
        setProgress(null);
      }
    }
  }
  return {requestTranscription, cancelTranscription, transcribing, isTranscribing, isCancelling, progress};
}
