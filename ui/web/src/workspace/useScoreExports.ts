import { useRef, useState } from "react";
import type { MouseEvent, RefObject } from "react";
import { isCurrentDocumentRevision } from "./document.js";
import { exportScoreDocument, exportSvgDocument } from "./native-files.js";
import type {
  DocumentSnapshot,
  ExportDpi,
  ExportFormat,
  ExportStatus,
  WorkspaceCopy,
} from "./types";

function exportFormatName(
  format: ExportFormat,
  dpi: ExportDpi,
  copy: WorkspaceCopy,
): string {
  if (format === "svg") return copy.formatSvg;
  if (format === "pdf") return copy.formatPdf;
  return copy.formatJpg(dpi ?? 96);
}

export function exportStatusText(status: ExportStatus, copy: WorkspaceCopy): string {
  const format = exportFormatName(status.format, status.dpi, copy);
  if (status.kind === "working") return copy.exportStarted(format, status.revision);
  if (status.kind === "cancelled") return copy.exportCancelled(format, status.revision);
  if (status.kind === "error") return copy.exportFailed(format, status.message);
  return copy.exported(
    format,
    status.revision,
    status.pageCount,
    status.filenames.slice(0, 3).join(", "),
    Math.max(0, status.filenames.length - 3),
    status.customMarkupOmitted,
  );
}

export function useScoreExports({ score, currentDocument, documentOpen, copyRef }: {
  score: DocumentSnapshot;
  currentDocument: RefObject<DocumentSnapshot>;
  documentOpen: boolean;
  copyRef: RefObject<WorkspaceCopy>;
}) {
  const [exportStatus, setExportStatus] = useState<ExportStatus | null>(null);
  const [isExporting, setIsExporting] = useState(false);
  const exportInProgress = useRef(false);
  const currentExportStatus = exportStatus
    && isCurrentDocumentRevision(score, exportStatus)
    ? exportStatus
    : null;
  async function exportDocument(format: ExportFormat, dpi: ExportDpi = null) {
    if (!documentOpen) return;
    if (exportInProgress.current) return;
    if ((format === "jpg" && dpi !== 96 && dpi !== 300) || (format !== "jpg" && dpi !== null)) return;
    const current = currentDocument.current;
    const identity = { documentId: current.id, revision: current.revision };
    const operation = { ...identity, format, dpi };
    exportInProgress.current = true;
    setIsExporting(true);
    setExportStatus({ kind: "working", ...operation });
    const isCurrent = () => isCurrentDocumentRevision(currentDocument.current, identity);
    try {
      const snapshot = { ...current, pageConfig: structuredClone(current.pageConfig) };
      const args = {
        documentId: snapshot.id,
        documentRevision: snapshot.revision,
        name: snapshot.name,
        code: snapshot.source,
        customCode: snapshot.customCode,
        pageConfig: snapshot.pageConfig,
      };
      const suggestedPath = snapshot.suggestedPath ?? snapshot.path;
      const receipt = format === "svg"
        ? await exportSvgDocument(args, suggestedPath, snapshot.name)
        : await exportScoreDocument(args, suggestedPath, snapshot.name, format, dpi);
      if (!isCurrent()) return;
      if (receipt === null) {
        setExportStatus({
          kind: "cancelled",
          ...operation,
        });
        return;
      }
      if (
        receipt.documentId !== snapshot.id
        || receipt.revision !== snapshot.revision
        || (format !== "svg"
          && (
            !("format" in receipt)
            || receipt.format !== format
            || !("dpi" in receipt)
            || receipt.dpi !== dpi
          ))
        || !Number.isSafeInteger(receipt.pageCount)
        || receipt.pageCount < 1
        || !Array.isArray(receipt.filenames)
        || receipt.filenames.length !== (format === "pdf" ? 1 : receipt.pageCount)
        || !receipt.filenames.every((name) => typeof name === "string" && name.length > 0)
        || typeof receipt.customMarkupOmitted !== "boolean"
      ) {
        throw new Error(copyRef.current.exportInvalidResult);
      }
      setExportStatus({ ...receipt, ...operation, kind: "complete" });
    } catch (error) {
      if (isCurrent()) {
        setExportStatus({
          kind: "error",
          ...operation,
          message: error instanceof Error ? error.message : String(error),
        });
      }
    } finally {
      exportInProgress.current = false;
      setIsExporting(false);
    }
  }

  function startExport(
    event: MouseEvent<HTMLButtonElement>,
    format: ExportFormat,
    dpi: ExportDpi = null,
  ) {
    const menu = event.currentTarget.closest("details");
    if (menu) {
      menu.open = false;
      menu.querySelector("summary")?.focus();
    }
    void exportDocument(format, dpi);
  }

  return { isExporting, currentExportStatus, startExport };
}
