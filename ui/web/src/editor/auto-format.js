import { Annotation, EditorSelection, EditorState } from "@codemirror/state";

import { formatAfterInput } from "./jp-format.js";

export const autoFormatApplied = Annotation.define();

/** @param {number[]} points @param {number} mainIndex */
export function selectionFromPoints(points, mainIndex) {
  const ranges = [];
  for (let index = 0; index < points.length; index += 2) {
    ranges.push(EditorSelection.range(points[index], points[index + 1]));
  }
  return EditorSelection.create(ranges, mainIndex);
}

export function jpsAutoFormatFilter() {
  return EditorState.transactionFilter.of((transaction) => {
    if (
      !transaction.docChanged
      || transaction.annotation(autoFormatApplied)
      || transaction.isUserEvent("input.type.compose")
      || !transaction.isUserEvent("input")
    ) return transaction;

    const points = transaction.newSelection.ranges.flatMap((range) => [range.anchor, range.head]);
    const formatted = formatAfterInput(
      transaction.newDoc.toString(),
      transaction.newSelection.main.head,
      points,
    );
    if (!formatted.changed) return transaction;

    return [
      transaction,
      {
        changes: {
          from: 0,
          to: transaction.newDoc.length,
          insert: formatted.text.replaceAll("\n", transaction.startState.lineBreak),
        },
        selection: selectionFromPoints(formatted.positions, transaction.newSelection.mainIndex),
        sequential: true,
        annotations: autoFormatApplied.of(true),
      },
    ];
  });
}
