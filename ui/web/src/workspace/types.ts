import type { inspectPdfDocument } from "../reference/pdf-runtime";
import type { createDocumentSession } from "./document.js";
import type { createLatestPreviewQueue } from "./preview-queue.js";
import type { readPreferences } from "./preferences.js";
import type { createReferenceSet } from "./reference-set.js";
import type { Language, messages } from "./i18n";

export type WorkspaceCopy = (typeof messages)[Language];

export type WorkspacePreferences = ReturnType<typeof readPreferences>;

export type WorkspaceMode = WorkspacePreferences["mode"];

export type LayoutId = "N1" | "N2" | "T1" | "T2";

export type PaneId = "editor" | "preview" | "reference";

export type FocusPane = PaneId | null;

export type LifecycleAction = "new" | "open" | "examples" | "close-document" | "exit" | "transcribe-new";

export type DialogKind = "new" | "dirty" | "settings-dirty" | "examples" | "recovery" | "reference-import" | "preferences" | null;

export type CatalogKind = "example" | "working-copy";

export type CatalogDocument = { name: string; kind: CatalogKind };

export type NewScoreFields = {
  title: string;
  subtitle: string;
  lyricist: string;
  composer: string;
  otherAuthors: string;
  keyNote: string;
  keyAccidental: "" | "#" | "$";
  beatNumerator: number;
  beatDenominator: number;
  tempo: string;
};

export type SourcePosition = { line: number; column: number; offset: number };

export type SourceSpan = { start: SourcePosition; end: SourcePosition };

export type RenderDiagnostic = {
  code: string;
  message: string;
  severity: string;
  span?: SourceSpan;
  recovery?: string;
};

export type RenderedPage = {
  page_index: number;
  page_count: number;
  page_width: number;
  page_height: number;
  svg: string;
  source_offset_unit: "codepoint";
  events: Array<{
    event_index: number;
    event_kind: string;
    source_span: SourceSpan;
    voice: number;
    row: number;
    slot: number;
    x: number;
    y: number;
  }>;
  lyrics: Array<{
    source_spans: SourceSpan[];
    voice: number;
    row: number;
    slot: number;
    verse: number;
    annotation: boolean;
    x: number;
    y: number;
  }>;
  diagnostics: RenderDiagnostic[];
  custom_markup_omitted: boolean;
};

export type PageRenderResponse = {
  result?: RenderedPage;
  status: "ok" | "error";
  error?: { code: string; message: string; page_count?: number };
};

export type CodecResponse<T> = {
  status: "ok" | "error";
  result?: T;
  error?: { code: string; message: string };
};

export type LoadedJps = {
  document: {
    name: string;
    code: string;
    custom_code: string;
    page_config: Record<string, unknown>;
    wrapper_fields: Record<string, unknown>;
    json_wrapped: boolean;
    encoding_repaired: boolean;
  };
};

export type SerializedJps = { text: string };

export type ExportFormat = "svg" | "pdf" | "jpg" | "png";

export type ExportDpi = 96 | 300 | null;

export type FontAvailability = Record<string, { family: string; fallback: string; available: boolean }>;
export type FontSources = WorkspacePreferences["fontSources"];
export type EngineCapabilities = { ocr: boolean; png_export: boolean; fonts?: FontAvailability };

export type ExportReceipt = {
  documentId: string;
  revision: number;
  format: ExportFormat;
  dpi: ExportDpi;
  pageCount: number;
  filenames: string[];
  customMarkupOmitted: boolean;
};

export type ExportStatus =
  | ({ kind: "working" } & Pick<
    ExportReceipt,
    "documentId" | "revision" | "format" | "dpi"
  >)
  | ({ kind: "cancelled" } & Pick<
    ExportReceipt,
    "documentId" | "revision" | "format" | "dpi"
  >)
  | ({ kind: "complete" } & ExportReceipt)
  | ({ kind: "error" } & Pick<
    ExportReceipt,
    "documentId" | "revision" | "format" | "dpi"
  > & { message: string });

export type RecoveryDraft = { kind: "new"; name: string; fields: NewScoreFields };

export type RecoverySnapshot = {
  document: {
    name: string;
    source: string;
    savedSource: string;
    savedFileText: string | null;
    suggestedPath: string | null;
    wrapperFields: Record<string, unknown>;
    customCode: string;
    pageConfig: Record<string, unknown>;
    savedPageConfig: Record<string, unknown>;
    jsonWrapped: boolean;
    revision: number;
  };
  draft: RecoveryDraft | null;
  references: ReturnType<typeof createReferenceSet>;
};

export type RenderDiagnostics = NonNullable<PageRenderResponse["result"]>["diagnostics"];

export type DocumentSnapshot = ReturnType<typeof createDocumentSession>;

export type TranscriptionIssue = { code: string; page: number; detail: string; regions: number[][]; confidence?: number | null; source_start?: number | null; source_end?: number | null };

export type TranscriptionDraft = { jps: string; page_count: number; page_dimensions?: {width:number; height:number}[]; issues: TranscriptionIssue[] };

export type PreviewRequest = { document: DocumentSnapshot; pageIndex: number };

export type PreviewQueue = ReturnType<typeof createLatestPreviewQueue<PreviewRequest, RenderedPage>>;

export type PageCache = {
  documentId: string;
  revision: number;
  pageCount: number;
  pages: Map<number, RenderedPage>;
};

export type SourceAnchor = {
  kind: "event" | "lyric";
  pageIndex?: number;
  x: number;
  y: number;
  row?: number;
  sourceSpans: SourceSpan[];
  eventIndex?: number;
};

export type StagedReferenceImage = {
  id: string;
  path: string;
  name: string;
  mimeType: "image/png" | "image/jpeg";
  byteLength: number;
  width: number;
  height: number;
  orientation: number;
};

export type StagedReferencePdf = {
  id: string;
  path: string;
  name: string;
  byteLength: number;
  sha256: string;
};

export type StagedReferenceAssets = {
  images: StagedReferenceImage[];
  pdfs: StagedReferencePdf[];
  order: string[];
};

export type PdfImport = Awaited<ReturnType<typeof inspectPdfDocument>>;

export type ReferencePdf = Pick<PdfImport, "id" | "name" | "byteLength" | "sha256" | "pageCount">;

export type ReferencePage = Omit<StagedReferenceImage, "path"> & { kind: "image" }
  | PdfImport["pages"][number];

export type PendingReferenceImport = {
  pages: ReferencePage[];
  pdfs: ReferencePdf[];
  sources: Record<string, string>;
  assetIds: string[];
};

export type Status =
  | { kind: "ready" | "changed" | "preferences" | "saved" | "notice" | "transcribing" }
  | {kind: "rendering"; completed?: number; pages?: number}
  | { kind: "rendered"; pages: number; elapsed?: number }
  | { kind: "transcribed"; issues: number }
  | { kind: "error"; message: string };
