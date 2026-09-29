import { useEffect, useLayoutEffect, useRef } from "react";

import {
  Compartment,
  EditorSelection,
  EditorState,
  StateEffect,
  StateField,
  Transaction,
  type Extension,
} from "@codemirror/state";
import {
  defaultKeymap,
  history,
  historyKeymap,
  isolateHistory,
  indentWithTab,
  redo,
  redoDepth,
  selectAll,
  undo,
  undoDepth,
} from "@codemirror/commands";
import {
  bracketMatching,
  defaultHighlightStyle,
  indentOnInput,
  syntaxHighlighting,
} from "@codemirror/language";
import {
  getSearchQuery,
  highlightSelectionMatches,
  openSearchPanel,
  search,
  searchKeymap,
  searchPanelOpen,
  setSearchQuery,
} from "@codemirror/search";
import {
  Decoration,
  drawSelection,
  dropCursor,
  EditorView,
  highlightActiveLine,
  highlightActiveLineGutter,
  highlightSpecialChars,
  keymap,
  lineNumbers,
  rectangularSelection,
  type DecorationSet,
} from "@codemirror/view";

import type { Language } from "../workspace/i18n";
import { editorPhrases, messages } from "../workspace/i18n";
import { autoFormatApplied, jpsAutoFormatFilter, selectionFromPoints } from "./auto-format.js";
import { formatJpsSource } from "./jp-format.js";
import { jpsLanguage } from "./jps-language";
import { pageConfigField, pageConfigHistory, setPageConfig } from "./page-config-history.js";

const setNoteHighlight = StateEffect.define<{ from: number; to: number } | null>();
const noteHighlightField = StateField.define<DecorationSet>({
  create: () => Decoration.none,
  update(decorations, transaction) {
    for (const effect of transaction.effects) {
      if (!effect.is(setNoteHighlight)) continue;
      const range = effect.value;
      return range && range.from < range.to
        ? Decoration.set([Decoration.mark({ class: "note-click-highlight" }).range(range.from, range.to)])
        : Decoration.none;
    }
    if (transaction.docChanged || transaction.selection) return Decoration.none;
    return decorations.map(transaction.changes);
  },
});
const noteHighlightExtension: Extension = [
  noteHighlightField,
  EditorView.decorations.from(noteHighlightField),
];

type JpsEditorProps = {
  documentId: string;
  source: string;
  language: Language;
  pageConfig: Record<string, unknown>;
  onChange(source: string): void;
  onCursorChange(offset: number, focused: boolean): void;
  onPageConfigChange(pageConfig: Record<string, unknown>): void;
  onHistoryChange(canUndo: boolean, canRedo: boolean): void;
  onReady(handle: JpsEditorHandle | null): void;
};

export type JpsEditorHandle = {
  applyPageConfig(pageConfig: Record<string, unknown>): void;
  undo(): boolean;
  redo(): boolean;
  copy(): boolean;
  paste(): boolean;
  find(replace?: boolean): boolean;
  selectAll(): boolean;
  insertLast(): boolean;
  formatSource(): void;
  selectSourceRange(from: number, to: number, highlight?: boolean): boolean;
  appendSource(source: string): void;
};

export function JpsEditor({
  documentId,
  source,
  language,
  pageConfig,
  onChange,
  onCursorChange,
  onPageConfigChange,
  onHistoryChange,
  onReady,
}: JpsEditorProps) {
  const host = useRef<HTMLDivElement>(null);
  const view = useRef<EditorView | null>(null);
  const sourceId = useRef(documentId);
  const onChangeRef = useRef(onChange);
  const onCursorChangeRef = useRef(onCursorChange);
  const onPageConfigChangeRef = useRef(onPageConfigChange);
  const onHistoryChangeRef = useRef(onHistoryChange);
  const onReadyRef = useRef(onReady);
  const lastInsertion = useRef<string | null>(null);
  const locale = useRef(new Compartment());
  const lineSeparator = useRef(new Compartment());
  const extensions = useRef<Extension[]>([]);

  onChangeRef.current = onChange;
  onCursorChangeRef.current = onCursorChange;
  onPageConfigChangeRef.current = onPageConfigChange;
  onHistoryChangeRef.current = onHistoryChange;
  onReadyRef.current = onReady;

  function buildExtensions(
    doc: string,
    editorLanguage: Language,
    initialPageConfig: Record<string, unknown>,
  ): Extension[] {
    return [
      lineSeparator.current.of(EditorState.lineSeparator.of(lineSeparatorFor(doc))),
      locale.current.of(localeExtensions(editorLanguage)),
      keymap.of([{
        key: "Mod-e",
        run: (editor) => insertLast(editor),
      }, {
        key: "Mod-f",
        run: (editor) => showSearch(editor),
        scope: "editor search-panel",
      }]),
      lineNumbers(),
      highlightActiveLineGutter(),
      highlightSpecialChars(),
      history(),
      drawSelection(),
      dropCursor(),
      EditorState.allowMultipleSelections.of(true),
      indentOnInput(),
      bracketMatching(),
      rectangularSelection(),
      highlightActiveLine(),
      highlightSelectionMatches(),
      noteHighlightExtension,
      search(),
      keymap.of([...defaultKeymap, indentWithTab, ...searchKeymap, ...historyKeymap]),
      syntaxHighlighting(defaultHighlightStyle, { fallback: true }),
      EditorView.lineWrapping,
      pageConfigHistory(initialPageConfig),
      jpsLanguage,
      jpsAutoFormatFilter(),
      EditorView.updateListener.of((update) => {
        onHistoryChangeRef.current(undoDepth(update.state) > 0, redoDepth(update.state) > 0);
        if (update.docChanged) onChangeRef.current(update.state.sliceDoc());
        if (update.docChanged || update.selectionSet) {
          onCursorChangeRef.current(update.state.selection.main.head, update.view.hasFocus);
        }
        const before = update.startState.field(pageConfigField);
        const after = update.state.field(pageConfigField);
        if (before !== after) onPageConfigChangeRef.current(after);
      }),
      EditorView.domEventHandlers({
        focus: (_event, editor) => {
          onCursorChangeRef.current(editor.state.selection.main.head, true);
          return false;
        },
        blur: (_event, editor) => {
          onCursorChangeRef.current(editor.state.selection.main.head, false);
          return false;
        },
      }),
    ];
  }

  useLayoutEffect(() => {
    const parent = host.current;
    if (!parent) return;
    extensions.current = buildExtensions(source, language, pageConfig);
    const editor = new EditorView({
      state: EditorState.create({
        doc: source,
        extensions: extensions.current,
      }),
      parent,
    });
    view.current = editor;
    onHistoryChangeRef.current(false, false);
    onReadyRef.current({
      applyPageConfig(nextPageConfig) {
        if (editor.state.field(pageConfigField) === nextPageConfig) return;
        editor.dispatch({
          effects: setPageConfig.of(nextPageConfig),
          annotations: [
            Transaction.userEvent.of("input.settings"),
            isolateHistory.of("full"),
          ],
        });
      },
      undo() {
        editor.focus();
        return undo(editor);
      },
      redo() {
        editor.focus();
        return redo(editor);
      },
      copy() {
        editor.focus();
        return document.execCommand("copy");
      },
      paste() {
        editor.focus();
        return document.execCommand("paste");
      },
      find(replace = false) {
        return showSearch(editor, replace);
      },
      selectAll() {
        editor.focus();
        return selectAll(editor);
      },
      insertLast() {
        return insertLast(editor);
      },
      formatSource() {
        applySourceFormatting();
      },
      selectSourceRange(from, to, highlight = true) {
        if (
          !Number.isSafeInteger(from)
          || !Number.isSafeInteger(to)
          || from < 0
          || from > to
          || to > editor.state.doc.length
        ) return false;
        editor.focus();
        editor.dispatch({
          selection: highlight ? EditorSelection.cursor(from) : EditorSelection.range(from, to),
          effects: setNoteHighlight.of(highlight ? { from, to } : null),
          scrollIntoView: true,
        });
        return true;
      },
      appendSource(text) {
        editor.dispatch({
          changes: { from: editor.state.doc.length, insert: text },
          selection: EditorSelection.cursor(editor.state.doc.length + text.length),
          scrollIntoView: true,
          annotations: [
            Transaction.userEvent.of("input.transcription"),
            autoFormatApplied.of(true),
          ],
        });
        editor.focus();
      },
    });
    return () => {
      editor.destroy();
      onReadyRef.current(null);
      view.current = null;
    };
  }, []);

  function showSearch(editor: EditorView, replace = false): boolean {
    const query = searchPanelOpen(editor.state) ? getSearchQuery(editor.state) : null;
    host.current?.classList.toggle("find-only", !replace);
    openSearchPanel(editor);
    if (query) editor.dispatch({ effects: setSearchQuery.of(query) });
    editor.requestMeasure();
    return true;
  }

  useEffect(() => {
    const editor = view.current;
    if (!editor) return;
    if (sourceId.current !== documentId) {
      sourceId.current = documentId;
      extensions.current = buildExtensions(source, language, pageConfig);
      editor.setState(EditorState.create({ doc: source, extensions: extensions.current }));
      onHistoryChangeRef.current(false, false);
      return;
    }
    if (editor.state.sliceDoc() !== source) {
      editor.dispatch({
        changes: { from: 0, to: editor.state.doc.length, insert: source },
        annotations: Transaction.addToHistory.of(false),
      });
    }
  }, [documentId, source]);

  useEffect(() => {
    const editor = view.current;
    if (!editor) return;
    editor.dispatch({
      effects: locale.current.reconfigure(localeExtensions(language)),
      annotations: Transaction.addToHistory.of(false),
    });
  }, [language]);

  function insertLast(editor: EditorView) {
    const insertion = lastInsertion.current;
    if (insertion === null) return false;
    insertSnippet(editor, insertion);
    return true;
  }

  function insertSnippet(editor: EditorView, snippet: string) {
    const range = editor.state.selection.main;
    const cursorOffset = snippet === '""' ? 1 : snippet.length;
    editor.dispatch({
      changes: { from: range.from, to: range.to, insert: snippet },
      selection: EditorSelection.cursor(range.from + cursorOffset),
      userEvent: "input.type",
      scrollIntoView: true,
    });
    editor.focus();
    lastInsertion.current = snippet;
  }

  function applySourceFormatting() {
    const editor = view.current;
    if (!editor) return;
    const selection = editor.state.selection;
    const points = selection.ranges.flatMap((range) => [range.anchor, range.head]);
    const formatted = formatJpsSource(editor.state.doc.toString(), points);
    if (formatted.text === editor.state.doc.toString()) return;
    editor.dispatch({
      changes: {
        from: 0,
        to: editor.state.doc.length,
        insert: formatted.text.replaceAll("\n", editor.state.lineBreak),
      },
      selection: selectionFromPoints(formatted.positions, selection.mainIndex),
      annotations: [
        Transaction.userEvent.of("input.format"),
        autoFormatApplied.of(true),
      ],
    });
    editor.focus();
  }

  return (
    <div className="source-editor">
      <div className="code-editor" ref={host} />
    </div>
  );
}

function localeExtensions(language: Language): Extension[] {
  return [
    EditorState.phrases.of(editorPhrases[language]),
    EditorView.contentAttributes.of({
      "aria-label": messages[language].source,
      spellcheck: "false",
    }),
  ];
}

function lineSeparatorFor(source: string) {
  return source.match(/\r\n|\r|\n/)?.[0] ?? "\n";
}
