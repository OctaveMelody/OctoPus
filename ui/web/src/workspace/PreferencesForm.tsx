import type { Dispatch, SetStateAction } from "react";
import type { FontAvailability, WorkspaceCopy, WorkspacePreferences } from "./types";
import { fontFamilyNames } from "./i18n";
import type { Language } from "./i18n";

const roles = [
  ["heiti-1", "fontHeiTi1", "MiSans"], ["heiti-2", "fontHeiTi2", "LXGW Neo XiHei"],
  ["songti", "fontSongTi", "SimZhiSong"], ["kaiti", "fontKaiTi", "LXGW WenKai"],
  ["fangsong", "fontFangSong", "Zhuque Fangsong"],
] as const;

export function PreferencesForm({ copy, preferences, fonts, onChange, onClose }: {
  copy: WorkspaceCopy; preferences: WorkspacePreferences; fonts?: FontAvailability;
  onChange: Dispatch<SetStateAction<WorkspacePreferences>>; onClose: () => void;
}) {
  const familyName = (family: string) => fontFamilyNames[preferences.language][family] ?? family;
  return <>
    <h2 id="lifecycle-dialog-title">{copy.preferences}</h2>
    <fieldset className="preferences-section preferences-language">
      <legend>{copy.language}</legend>
      <div className="preferences-language-options">
        {([ ["en", copy.english], ["zh-CN", copy.chinese] ] as const).map(([language, label]) =>
          <label key={language}><input type="radio" name="preferences-language" value={language}
            checked={preferences.language === language}
            onChange={() => onChange(current => ({ ...current, language: language as Language }))} />
            {label}</label>)}
      </div>
    </fieldset>
    <div className="preferences-section preferences-samples-section">
      <label className="preferences-checkbox"><input type="checkbox"
        checked={preferences.displaySamplesLibrary}
        onChange={event => onChange(current => ({
          ...current, displaySamplesLibrary: event.target.checked,
        }))} />{copy.displaySamplesLibrary}</label>
    </div>
    <fieldset className="preferences-section preferences-font-section">
      <legend>{copy.fontOutput}</legend>
      <p>{copy.fontPreferenceHelp}</p>
      {!fonts && <p role="status">{copy.fontChecking}</p>}
      <div className="preferences-font-table-wrap">
        <table className="preferences-fonts">
        <thead><tr>
          <th scope="col">{copy.fontColumn}</th>
          <th scope="col">{copy.osFont}</th>
          <th scope="col">{copy.bundledFont}</th>
        </tr></thead>
        <tbody>
      {roles.map(([role, label, fallback]) => {
        const available = fonts?.[role]?.available === true;
        const selected = preferences.fontSources[role] ?? "system";
        const osFamily = fonts?.[role]?.family ?? copy[label];
        const fallbackFamily = fonts?.[role]?.fallback ?? fallback;
        return <tr key={role}>
          <th scope="row" style={{ fontFamily: JSON.stringify(osFamily) }}>{copy[label]}</th>
          {(["system", "fallback"] as const).map(source => {
            const family = source === "system" ? osFamily : fallbackFamily;
            const familyLabel = familyName(family);
            return <td key={source}>
              <label className="preferences-font-choice">
                <input type="radio" name={"font-source-" + role} value={source}
                  checked={selected === source}
                  onChange={() => onChange(current => ({
                    ...current, fontSources: { ...current.fontSources, [role]: source },
                  }))} />
                <span style={{ fontFamily: JSON.stringify(family) }}>{familyLabel}</span>
                {source === "system" && fonts && !available &&
                  <small className="preferences-font-unavailable">{copy.fontUnavailable}</small>}
              </label>
            </td>;
          })}
        </tr>;
      })}
        </tbody>
        </table>
      </div>
    </fieldset>
    <div className="dialog-actions preferences-actions">
      <button onClick={onClose} type="button">{copy.done}</button>
    </div>
  </>;
}
