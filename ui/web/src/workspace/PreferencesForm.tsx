import { useState } from "react";
import type { Dispatch, KeyboardEvent, SetStateAction } from "react";
import type { EngineCapabilities, FontAvailability, WorkspaceCopy, WorkspacePreferences } from "./types";
import { fontFamilyNames } from "./i18n";
import type { Language } from "./i18n";

const roles = [
  ["heiti-1", "fontHeiTi1", "MiSans"], ["heiti-2", "fontHeiTi2", "LXGW Neo XiHei"],
  ["songti", "fontSongTi", "SimZhiSong"], ["kaiti", "fontKaiTi", "LXGW WenKai"],
  ["fangsong", "fontFangSong", "Zhuque Fangsong"],
] as const;

export function PreferencesForm({ copy, preferences, fonts, ocrBackends, onChange, onClose }: {
  copy: WorkspaceCopy; preferences: WorkspacePreferences; fonts?: FontAvailability;
  ocrBackends?: EngineCapabilities["ocr_backends"];
  onChange: Dispatch<SetStateAction<WorkspacePreferences>>; onClose: () => void;
}) {
  const familyName = (family: string) => fontFamilyNames[preferences.language][family] ?? family;
  const [activeTab, setActiveTab] = useState<"general" | "transcription">("general");
  const handleTabKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const tabs = ["general", "transcription"] as const;
    const current = tabs.indexOf(activeTab);
    const next = event.key === "ArrowRight" ? tabs[(current + 1) % tabs.length]
      : event.key === "ArrowLeft" ? tabs[(current + tabs.length - 1) % tabs.length]
        : event.key === "Home" ? tabs[0] : event.key === "End" ? tabs[tabs.length - 1] : null;
    if (!next) return;
    event.preventDefault();
    setActiveTab(next);
    event.currentTarget.querySelector<HTMLButtonElement>(`[data-preferences-tab="${next}"]`)
      ?.focus();
  };
  return <>
    <h2 id="lifecycle-dialog-title">{copy.preferences}</h2>
    <div aria-label={copy.preferencesTabs} className="preferences-tabs" onKeyDown={handleTabKeyDown}
      role="tablist">
      {(["general", "transcription"] as const).map(tab => <button
        aria-controls={`preferences-panel-${tab}`} aria-selected={activeTab === tab}
        data-preferences-tab={tab} id={`preferences-tab-${tab}`} key={tab}
        onClick={() => setActiveTab(tab)} role="tab" tabIndex={activeTab === tab ? 0 : -1}
        type="button">{tab === "general" ? copy.generalTab : copy.transcriptionTab}</button>)}
    </div>
    <section aria-labelledby="preferences-tab-general" className="preferences-tab-panel"
      hidden={activeTab !== "general"} id="preferences-panel-general" role="tabpanel" tabIndex={0}>
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
          return <fieldset key={role}><legend style={{ fontFamily: JSON.stringify(selectedFamily) }}>{copy[label]}</legend>
            {(["system", "fallback"] as const).map(source => <label key={source}>
              <input type="radio" name={`font-source-${role}`} value={source}
                checked={selected === source} disabled={source === "system" && !available}
                onChange={() => onChange(current => ({ ...current,
                  fontSources: { ...current.fontSources, [role]: source },
                }))} />
              {source === "system" ? copy.osFont : copy.bundledFont}
              <span style={{ fontFamily: JSON.stringify(source === "system" ? osFamily : fallbackFamily) }}>{source === "system"
                ? `${familyName(fonts?.[role]?.family ?? copy[label])}${available ? "" : ` (${copy.fontUnavailable})`}`
                : familyName(fonts?.[role]?.fallback ?? fallback)}</span>
            </label>)}
          </fieldset>;
        })}
      </div>
    </section>
    <section aria-labelledby="preferences-tab-transcription" className="preferences-tab-panel"
      hidden={activeTab !== "transcription"} id="preferences-panel-transcription"
      role="tabpanel" tabIndex={0}>
      <h3>{copy.transcriptionBackendTitle}</h3><p>{copy.transcriptionBackendHelp}</p>
      <fieldset className="preferences-ocr-backends"><legend>{copy.transcriptionBackendTitle}</legend>
        {(["rapidocr-onnxruntime", "rapidocr-onnx"] as const).map(backend => {
          const available = ocrBackends?.[backend];
          return <label key={backend}>
            <input checked={preferences.ocrBackend === backend} disabled={available === false}
              name="ocr-backend" onChange={() => onChange(current => ({
                ...current, ocrBackend: backend,
              }))} type="radio" value={backend} />
            <span>{backend === "rapidocr-onnxruntime"
              ? "rapidocr-onnxruntime" : "RapidOCR + ONNX"}</span>
            {available === false && <small>{copy.backendUnavailable}</small>}
          </label>;
        })}
      </fieldset>
    </section>
    <div className="dialog-actions preferences-actions"><button onClick={onClose} type="button">{copy.done}</button></div>
  </>;
}
