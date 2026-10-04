import { useEffect, useRef, useState } from "react";

import { createSourceDiagnosticsQueue } from "../editor/source-diagnostics.js";
import type { CodecResponse, DocumentSnapshot, RenderDiagnostic } from "./types";

type ParsedSource = {diagnostics: RenderDiagnostic[]; source_offset_unit: "codepoint"};

export function useSourceDiagnostics({score, enabled, errorMessage, onError}: {
  score: DocumentSnapshot;
  enabled: boolean;
  errorMessage: string;
  onError?: (message: string) => void;
}) {
  const [accepted, setAccepted] = useState<{
    documentId: string; revision: number; source: string; diagnostics: RenderDiagnostic[];
  } | null>(null);
  const callback = useRef({errorMessage, onError});
  callback.current = {errorMessage, onError};

  useEffect(() => {
    const queue = createSourceDiagnosticsQueue(async (request: DocumentSnapshot) => {
      const core = window.__TAURI__?.core;
      if (!core) return null;
      const response = await core.invoke<CodecResponse<ParsedSource>>("parse_score", {
        args: {documentId: request.id, documentRevision: request.revision, name: request.name,
          code: request.source, customCode: "", pageConfig: {}},
      });
      if (response.status !== "ok" || response.result?.source_offset_unit !== "codepoint"
        || !Array.isArray(response.result.diagnostics)) {
        throw new Error(response.error?.message ?? callback.current.errorMessage);
      }
      return response.result;
    }, (request, result) => {
      if (result) setAccepted({documentId: request.id, revision: request.revision,
        source: request.source, diagnostics: result.diagnostics});
    }, (error) => {
      callback.current.onError?.(error instanceof Error ? error.message : callback.current.errorMessage);
    });
    if (enabled) queue.request(score);
    return () => queue.cancel();
  }, [score.id, score.revision, score.source, score.name, enabled]);

  const current = enabled && accepted?.documentId === score.id
    && accepted.revision === score.revision && accepted.source === score.source;
  return {diagnostics: current ? accepted.diagnostics : [],
    diagnosticsSource: current ? accepted.source : null};
}
