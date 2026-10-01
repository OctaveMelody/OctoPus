import type { Dispatch, SetStateAction } from "react";
import type { FontAvailability, WorkspaceCopy, WorkspacePreferences } from "./types";
import type { Language } from "./i18n";

const roles = [
  ["heiti-1", "HeiTi-1", "MiSans"], ["heiti-2", "HeiTi-2", "LXGW Neo XiHei"],
  ["songti", "SongTi", "SimZhiSong"], ["kaiti", "KaiTi", "LXGW WenKai"],
  ["fangsong", "FangSong", "Zhuque Fangsong"],
];

export function PreferencesForm({ copy, preferences, fonts, onChange, onClose }: {
  copy: WorkspaceCopy; preferences: WorkspacePreferences; fonts?: FontAvailability;
  onChange: Dispatch<SetStateAction<WorkspacePreferences>>; onClose: () => void;
}) {
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
        return <fieldset key={role}><legend>{label}</legend>
          {(["system", "fallback"] as const).map(source => <label key={source}>
            <input type="radio" name={`font-source-${role}`} value={source}
              checked={selected === source} disabled={source === "system" && !available}
              onChange={() => onChange(current => ({ ...current,
                fontSources: { ...current.fontSources, [role]: source },
              }))} />
            {source === "system" ? copy.osFont : copy.bundledFont}
            <span>{source === "system"
              ? `${fonts?.[role]?.family ?? label}${available ? "" : ` (${copy.fontUnavailable})`}`
              : fonts?.[role]?.fallback ?? fallback}</span>
          </label>)}
        </fieldset>;
      })}
    </div>
    <div className="dialog-actions"><button onClick={onClose} type="button">{copy.done}</button></div>
  </>;
}
