import { invertedEffects } from "@codemirror/commands";
import { Facet, StateEffect, StateField } from "@codemirror/state";

/** @typedef {Record<string, unknown>} PageConfig */

/** @type {import("@codemirror/state").StateEffectType<PageConfig>} */
export const setPageConfig = StateEffect.define();

const initialPageConfig = Facet.define({
  combine: (values) => values[values.length - 1] ?? {},
});

export const pageConfigField = StateField.define({
  create: (state) => state.facet(initialPageConfig),
  update(value, transaction) {
    for (const effect of transaction.effects) {
      if (effect.is(setPageConfig)) return effect.value;
    }
    return value;
  },
});

/** @param {PageConfig} pageConfig */
export function pageConfigHistory(pageConfig) {
  return [
    initialPageConfig.of(pageConfig),
    pageConfigField,
    invertedEffects.of((transaction) => (
      transaction.effects.some((effect) => effect.is(setPageConfig))
        ? [setPageConfig.of(transaction.startState.field(pageConfigField))]
        : []
    )),
  ];
}
