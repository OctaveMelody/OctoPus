import type { WorkspaceCopy } from "./types";

export function PanelControls({ copy, name, maximized, onToggle, onClose }: {
  copy: WorkspaceCopy; name: string; maximized: boolean;
  onToggle(): void; onClose(): void;
}) {
  const toggleLabel = `${maximized ? copy.restorePanel : copy.maximizePanel}: ${name}`;
  const closeLabel = `${copy.closePanel}: ${name}`;
  return <div className="panel-window-controls">
    <button type="button" title={toggleLabel} aria-label={toggleLabel}
      aria-pressed={maximized} onClick={onToggle}>
      <svg aria-hidden="true" width="14" height="14" viewBox="0 0 16 16"
        fill="none" stroke="currentColor" strokeWidth="1.3">
        {maximized ? <path d="M5 5V2h9v9h-3 M2 5h9v9H2z" />
          : <rect x="2" y="2" width="12" height="12" />}
      </svg>
    </button>
    <button type="button" title={closeLabel} aria-label={closeLabel} onClick={onClose}>×</button>
  </div>;
}
