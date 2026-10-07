import type { ReactNode, RefObject } from "react";
import type { HelpDestination, UpdateResult } from "./help-actions.js";
import type { WorkspaceCopy } from "./types";

export function InformationDialog({ kind: informationDialog, dialogRef: informationDialogRef,
  copy, checkingUpdate, updateResult, updateError, browserError, onClose, openHelp, brand }: {
  kind: "about" | "update" | "browser-error" | null;
  dialogRef: RefObject<HTMLDialogElement | null>;
  copy: WorkspaceCopy;
  checkingUpdate: boolean;
  updateResult: UpdateResult | null;
  updateError: string;
  browserError: string;
  onClose: () => void;
  openHelp: (destination: HelpDestination) => Promise<void>;
  brand: ReactNode;
}) {
  return (
      <dialog
        aria-labelledby="information-dialog-title"
        className="lifecycle-dialog information-dialog"
        onCancel={(event) => {
          event.preventDefault();
          onClose();
        }}
        ref={informationDialogRef}
      >
        {informationDialog === "update" && (
          <section>
            <h2 id="information-dialog-title">{copy.checkForUpdate}</h2>
            {checkingUpdate && <p role="status">{copy.checkingUpdate}</p>}
            {updateError && <p role="alert">{copy.updateFailed} {updateError}</p>}
            {updateResult && <>
              <p>{updateResult.status === "available" ? copy.updateAvailable
                : updateResult.status === "up_to_date" ? copy.updateCurrent
                : updateResult.status === "unknown_version" ? copy.updateUnknown : copy.updateUnavailable}</p>
              <p>{copy.installedVersion}: {updateResult.current_version}</p>
              {updateResult.latest_version && <p>{copy.latestVersion}: {updateResult.latest_version}</p>}
            </>}
            <p><a href="https://github.com/OctaveMelody/OctoPus/releases" onClick={event => {
              event.preventDefault(); void openHelp("releases");
            }}>{copy.releases}</a></p>
            <div className="dialog-actions"><button autoFocus className="primary-button"
              onClick={() => onClose()} type="button">{copy.done}</button></div>
          </section>
        )}
        {informationDialog === "browser-error" && (
          <section>
            <h2 id="information-dialog-title">{copy.browserErrorTitle}</h2>
            <p role="alert">{browserError}</p>
            <div className="dialog-actions"><button autoFocus className="primary-button"
              onClick={() => onClose()} type="button">{copy.done}</button></div>
          </section>
        )}
        {informationDialog === "about" && (
          <section>
            <h2 id="information-dialog-title">{copy.aboutTitle}</h2>
            {brand}
            <p>v1.0-Beta</p>
            <p>{copy.aboutDescription}</p>
            <p><a href="https://github.com/OctaveMelody/OctoPus" onClick={event => {
              event.preventDefault(); void openHelp("home");
            }}>{copy.projectHome}</a></p>
            <h3>{copy.acknowledgments}</h3>
            <p><a href="http://zhipu.lezhi99.com" onClick={event => {
              event.preventDefault(); void openHelp("tomato_jianpu");
            }}>{copy.tomatoJianpu}</a>{" — "}{copy.tomatoCredits}</p>
            <p>{copy.transcriptionCredits}</p>
            <p>{copy.fontCredits}</p>
            <h3>{copy.licenseTitle}</h3>
            <p>{copy.licenseInformation}</p>
            <div className="dialog-actions">
              <button autoFocus className="primary-button" onClick={() => onClose()} type="button">
                {copy.done}
              </button>
            </div>
          </section>
        )}
      </dialog>
  );
}
