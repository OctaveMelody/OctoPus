import { useEffect, useRef, useState } from "react";

import {
  applyPageSettings,
  createPageSettingsDraft,
  pageSettingGroups,
  pageSettingsDraftChanged,
} from "./page-settings.js";
import { messages } from "./i18n";

type PageSettingsCopy = (typeof messages)["en"];

type PageSettingsProps = {
  config: Record<string, unknown>;
  copy: PageSettingsCopy;
  disabled: boolean;
  wrapped: boolean;
  settingsDirty: boolean;
  onDraftChange(dirty: boolean, config: Record<string, unknown>): void;
  onApply(config: Record<string, unknown>): void;
};

export function PageSettings({
  config,
  copy,
  disabled,
  wrapped,
  settingsDirty,
  onDraftChange,
  onApply,
}: PageSettingsProps) {
  const [draft, setDraft] = useState(() => createPageSettingsDraft(config));
  const dialogRef = useRef<HTMLDialogElement>(null);
  const onDraftChangeRef = useRef(onDraftChange);
  const change = applyPageSettings(config, draft);
  const draftChanged = pageSettingsDraftChanged(config, draft);
  onDraftChangeRef.current = onDraftChange;

  useEffect(() => {
    setDraft(createPageSettingsDraft(config));
    onDraftChangeRef.current(false, config);
  }, [config]);

  function updateField(key: string, value: string | number) {
    const nextDraft = { ...draft, [key]: value };
    const nextChange = applyPageSettings(config, nextDraft);
    setDraft(nextDraft);
    onDraftChange(nextChange.changed, nextChange.config);
  }

  function cancelDraft() {
    setDraft(createPageSettingsDraft(config));
    onDraftChange(false, config);
    dialogRef.current?.close();
  }

  function applyDraft() {
    onApply(change.config);
    onDraftChange(false, config);
  }

  function confirmDraft() {
    applyDraft();
    dialogRef.current?.close();
  }

  return (
    <>
      <button
        className="page-settings-trigger"
        disabled={disabled}
        onClick={() => dialogRef.current?.showModal()}
        type="button"
      >
        {copy.pageSettings}
      </button>
      <dialog
        aria-labelledby="page-settings-title"
        className="page-settings-dialog"
        onCancel={(event) => {
          event.preventDefault();
          cancelDraft();
        }}
        ref={dialogRef}
      >
        <h2 id="page-settings-title">{copy.pageSettings}</h2>
        <div className="page-settings-body">
          {"_raw" in config && <p className="settings-note">{copy.pageSettingsRawPreserved}</p>}
          {(!wrapped && (settingsDirty || change.changed)) && (
            <p className="settings-note">{copy.pageSettingsWrapNotice}</p>
          )}
          <div className="page-settings-groups">
            {pageSettingGroups.map((group) => (
              <fieldset className="page-settings-group" key={group.key}>
                <legend>{settingText(copy, group.key)}</legend>
                {group.key === "pageSettingsFontsGroup" && (
                  <p className="settings-note">{copy.systemFontsNotice}</p>
                )}
                {group.fields.map((field) => (
                  <label className="page-settings-field" key={field.key}>
                    <span>
                      {settingText(copy, field.label)} <em>({String(field.defaultValue)})</em>
                    </span>
                    {field.kind === "select" ? (
                      <select
                        disabled={disabled}
                        onChange={(event) => updateField(field.key, event.target.value)}
                        value={String(draft[field.key] ?? field.defaultValue)}
                      >
                        {!field.options?.some((option) => option.value === String(draft[field.key])) && (
                          <option value={String(draft[field.key])}>
                            {copy.currentValue}: {String(draft[field.key])}
                          </option>
                        )}
                        {field.options?.map((option) => (
                          <option key={option.value} value={option.value}>
                            {settingText(copy, option.label)}
                          </option>
                        ))}
                      </select>
                    ) : (
                      <input
                        disabled={disabled}
                        max={field.max}
                        min={field.min}
                        onChange={(event) => updateField(field.key, event.target.value)}
                        step={1}
                        type="number"
                        value={String(draft[field.key] ?? field.defaultValue)}
                      />
                    )}
                  </label>
                ))}
              </fieldset>
            ))}
          </div>
          <div className="page-settings-actions">
            <button disabled={disabled || !draftChanged} onClick={applyDraft} type="button">
              {copy.applySettings}
            </button>
            <button disabled={disabled || !draftChanged} onClick={confirmDraft} type="button">
              {copy.done}
            </button>
            <button onClick={cancelDraft} type="button">{copy.cancel}</button>
          </div>
        </div>
      </dialog>
    </>
  );
}

function settingText(copy: PageSettingsCopy, key: string): string {
  const message = copy[key as keyof PageSettingsCopy];
  return typeof message === "string" ? message : key;
}
