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
    <label className="preferences-language">{copy.language} <select
      value={preferences.language} onChange={event => onChange(current => ({
        ...current, language: event.target.value as Language,
      }))}>
      <option value="en">{copy.english}</option><option value="zh-CN">{copy.chinese}</option>
    </select></label>
    <h3>{copy.fontOutput}</h3><p>{copy.fontPreferenceHelp}</p>
    {!fonts && <p role="status">{copy.fontChecking}</p>}
    <div className="preferences-fonts">
      {roles.map(([role, label, fallback]) => {
        const available = fonts?.[role]?.available === true;
        const selected = available ? preferences.fontSources[role] : "fallback";
        const osFamily = fonts?.[role]?.family ?? copy[label];
        const fallbackFamily = fonts?.[role]?.fallback ?? fallback;
        const selectedFamily = selected === "system" ? osFamily : fallbackFamily;
        return <fieldset key={role}>
          <legend style={{ fontFamily: JSON.stringify(selectedFamily) }}>{copy[label]}</legend>
          {(["system", "fallback"] as const).map(source => <label key={source}>
            <input type="radio" name={`font-source-${role}`} value={source}
              checked={selected === source} disabled={source === "system" && !available}
              onChange={() => onChange(current => ({
                ...current, fontSources: { ...current.fontSources, [role]: source },
              }))} />
            {source === "system" ? copy.osFont : copy.bundledFont}
            <span style={{ fontFamily: JSON.stringify(source === "system" ? osFamily : fallbackFamily) }}>
              {source === "system"
                ? `${familyName(fonts?.[role]?.family ?? copy[label])}${available ? "" : ` (${copy.fontUnavailable})`}`
                : familyName(fonts?.[role]?.fallback ?? fallback)}
            </span>
          </label>)}
        </fieldset>;
      })}
    </div>
    <div className="dialog-actions preferences-actions">
      <button onClick={onClose} type="button">{copy.done}</button>
    </div>
  </>;
}
