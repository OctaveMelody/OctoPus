import { EditorSelection, RangeSet, StateEffect, StateField, Transaction } from "@codemirror/state";
import { Decoration, EditorView, GutterMarker, gutter } from "@codemirror/view";

import { sourceDiagnosticRanges, wrappedContinuationCount } from "./source-diagnostics.js";

/** @typedef {ReturnType<typeof sourceDiagnosticRanges>[number]} DiagnosticRange */

/** @type {import('@codemirror/state').StateEffectType<DiagnosticRange[]>} */
export const setSourceDiagnostics = StateEffect.define();
export const sourceDiagnosticsField = StateField.define({
  create: () => buildDiagnostics([]),
  update(value, transaction) {
    if (transaction.docChanged) value = buildDiagnostics([]);
    for (const effect of transaction.effects) {
      if (effect.is(setSourceDiagnostics)) value = buildDiagnostics(effect.value);
    }
    return value;
  },
});

/** @param {DiagnosticRange[]} ranges */
function buildDiagnostics(ranges) {
  const marks = ranges.filter(({from, to}) => from < to).map((range) => (
    Decoration.mark({class: `source-diagnostic source-diagnostic-${range.severity}`,
      attributes: {title: range.message}}).range(range.from, range.to)
  ));
  /** @type {Map<number, DiagnosticRange[]>} */
  const lines = new Map();
  for (const range of ranges) {
    const onLine = lines.get(range.lineFrom) ?? [];
    onLine.push(range);
    lines.set(range.lineFrom, onLine);
  }
  return { decorations: Decoration.set(marks, true),
    markers: RangeSet.of(Array.from(lines, ([from, entries]) => (
      new DiagnosticMarker(entries).range(from)
    )), true) };
}

class DiagnosticMarker extends GutterMarker {
  /** @param {DiagnosticRange[]} ranges */
  constructor(ranges) { super(); this.ranges = ranges; }
  /** @param {GutterMarker} other */
  eq(other) {
    return other instanceof DiagnosticMarker && JSON.stringify(other.ranges) === JSON.stringify(this.ranges);
  }
  /** @param {EditorView} view */
  toDOM(view) {
    // CodeMirror hides all gutters from assistive technology. The matching
    // accessible jump buttons live outside the editor's decorative gutters.
    const button = document.createElement("span");
    button.setAttribute("aria-hidden", "true");
    const severity = this.ranges.some(({severity}) => severity === "error") ? "error"
      : this.ranges.some(({severity}) => severity === "warning") ? "warning" : "info";
    button.className = `source-diagnostic-button source-diagnostic-${severity}`;
    button.textContent = severity === "info" ? "●" : "!";
    button.title = this.ranges.map(({message}) => message).join("\n");
    button.addEventListener("mousedown", event => event.preventDefault());
    button.addEventListener("click", (event) => {
      event.preventDefault();
      const {from, to} = this.ranges[0];
      view.dispatch({selection: EditorSelection.range(from, to), scrollIntoView: true,
        annotations: Transaction.userEvent.of("select.diagnostic")});
      view.focus();
    });
    return button;
  }
}

export const sourceDiagnosticsExtension = [sourceDiagnosticsField,
  EditorView.decorations.from(sourceDiagnosticsField, ({decorations}) => decorations),
  gutter({class: "source-diagnostic-gutter",
    markers: (view) => view.state.field(sourceDiagnosticsField).markers,
    initialSpacer: () => new DiagnosticMarker([{from: 0, to: 0, lineFrom: 0,
      severity: "info", message: ""}]),
  }),
];

class WrapMarker extends GutterMarker {
  /** @param {number} count @param {number} lineHeight @param {string} label */
  constructor(count, lineHeight, label) { super(); this.count = count; this.lineHeight = lineHeight; this.label = label; }
  /** @param {GutterMarker} other */
  eq(other) {
    return other instanceof WrapMarker && other.count === this.count
      && other.lineHeight === this.lineHeight && other.label === this.label;
  }
  toDOM() {
    const marker = document.createElement("div");
    marker.className = "source-wrap-marker";
    marker.title = this.label;
    marker.setAttribute("aria-hidden", "true");
    marker.style.lineHeight = `${this.lineHeight}px`;
    marker.style.paddingTop = `${this.lineHeight}px`;
    for (let index = 0; index < this.count; index++) {
      const arrow = document.createElement("div");
      arrow.textContent = "↳";
      marker.append(arrow);
    }
    return marker;
  }
}

/** @param {() => string} label */
export function sourceWrappingGutter(label) {
  return gutter({class: "source-wrap-gutter",
    lineMarker: (view, line) => {
      const count = wrappedContinuationCount(line.height, view.defaultLineHeight);
      return count ? new WrapMarker(count, view.defaultLineHeight, label()) : null;
    },
    lineMarkerChange: (update) => update.geometryChanged || update.docChanged,
  });
}
