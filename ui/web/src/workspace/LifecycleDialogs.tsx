import type { Dispatch, SetStateAction } from "react";
import { PreferencesForm } from "./PreferencesForm";
import type { DocumentLifecycle } from "./useDocumentLifecycle";
import type { useReferenceAssets } from "./useReferenceAssets";
import type { WorkspaceCopy, WorkspacePreferences, FontAvailability,
  NewScoreFields } from "./types";

export function LifecycleDialogs({ lifecycle, referenceAssets, copy, preferences, setPreferences,
  fonts }: {
  lifecycle: DocumentLifecycle;
  referenceAssets: ReturnType<typeof useReferenceAssets>;
  copy: WorkspaceCopy;
  preferences: WorkspacePreferences;
  setPreferences: Dispatch<SetStateAction<WorkspacePreferences>>;
  fonts?: FontAvailability;
}) {
  const {activeDialog, activeDialogRef, dialogRef, dialogError, setDialogError,
    setActiveDialog, newFileName, setNewFileName, newScoreFields, setNewScoreFields,
    setNewScoreDraftActive, examples, examplesLoaded, exampleFilter, setExampleFilter,
    isSaving, saving, recoveryCandidate, recoveryError, isRecoveryActionRunning,
    resolveSettingsDraft, resolveDirtyAction, cancelDirtyAction, cancelSettingsDraftAction,
    createScore, chooseCatalogDocument, restoreRecovery, discardRecovery, continueWithoutRecovery} = lifecycle;
  const {pendingReferenceImport, isHandlingReferenceChoice, chooseReferenceImport} = referenceAssets;
  const visibleExamples = examples.filter(document =>
    document.name.toLowerCase().includes(exampleFilter.trim().toLowerCase()));
  return (
      <dialog
        aria-labelledby="lifecycle-dialog-title"
        className="lifecycle-dialog"
        onCancel={(event) => {
          if (referenceAssets.isChoosingImport() || referenceAssets.isCommitting()) {
            event.preventDefault();
            return;
          }
          if (saving.current) {
            event.preventDefault();
            return;
          }
          if (activeDialogRef.current === "recovery") {
            event.preventDefault();
            return;
          }
          event.preventDefault();
          if (activeDialogRef.current === "dirty") {
            cancelDirtyAction();
          } else if (activeDialogRef.current === "settings-dirty") {
            cancelSettingsDraftAction();
          } else if (activeDialogRef.current === "reference-import") {
            void chooseReferenceImport("cancel");
          } else {
            if (activeDialogRef.current === "new") setNewScoreDraftActive(false);
            setActiveDialog(null);
            setDialogError("");
          }
        }}
        ref={dialogRef}
      >
        {activeDialog === "preferences" && <PreferencesForm copy={copy}
          preferences={preferences} fonts={fonts}
          onChange={setPreferences} onClose={() => setActiveDialog(null)} />}
        {activeDialog === "dirty" && (
          <section>
            <h2 id="lifecycle-dialog-title">{copy.unsavedTitle}</h2>
            <p>{copy.unsavedPrompt}</p>
            {dialogError && <p className="dialog-error" role="alert">{dialogError}</p>}
            <div className="dialog-actions">
              <button disabled={isSaving} onClick={() => { void resolveDirtyAction("save"); }} type="button">
                {copy.save}
              </button>
              <button disabled={isSaving} onClick={() => { void resolveDirtyAction("discard"); }} type="button">
                {copy.discard}
              </button>
              <button disabled={isSaving} onClick={() => { void resolveDirtyAction("cancel"); }} type="button">
                {copy.cancel}
              </button>
            </div>
          </section>
        )}
        {activeDialog === "settings-dirty" && (
          <section>
            <h2 id="lifecycle-dialog-title">{copy.settingsDraftTitle}</h2>
            <p>{copy.settingsDraftPrompt}</p>
            {dialogError && <p className="dialog-error" role="alert">{dialogError}</p>}
            <div className="dialog-actions">
              <button className="primary-button" onClick={() => resolveSettingsDraft("apply")} type="button">
                {copy.applySettings}
              </button>
              <button onClick={() => resolveSettingsDraft("discard")} type="button">
                {copy.discardSettingsDraft}
              </button>
              <button onClick={() => resolveSettingsDraft("cancel")} type="button">
                {copy.cancel}
              </button>
            </div>
          </section>
        )}
        {activeDialog === "new" && (
          <form onSubmit={createScore}>
            <h2 id="lifecycle-dialog-title">{copy.newScoreTitle}</h2>
            <div className="new-score-fields">
              <label>{copy.fileName}<input autoFocus onChange={(event) => setNewFileName(event.target.value)} value={newFileName} /></label>
              <label>{copy.scoreTitle}<input required onChange={(event) => setNewScoreFields((current) => ({ ...current, title: event.target.value }))} value={newScoreFields.title} /></label>
              <label>{copy.subtitle}<input onChange={(event) => setNewScoreFields((current) => ({ ...current, subtitle: event.target.value }))} value={newScoreFields.subtitle} /></label>
              <label>{copy.lyricist}<input onChange={(event) => setNewScoreFields((current) => ({ ...current, lyricist: event.target.value }))} value={newScoreFields.lyricist} /></label>
              <label>{copy.composer}<input onChange={(event) => setNewScoreFields((current) => ({ ...current, composer: event.target.value }))} value={newScoreFields.composer} /></label>
              <label>{copy.otherAuthors}<input onChange={(event) => setNewScoreFields((current) => ({ ...current, otherAuthors: event.target.value }))} value={newScoreFields.otherAuthors} /></label>
              <label>{copy.keySignature}<span className="field-pair">
                <select onChange={(event) => setNewScoreFields((current) => ({ ...current, keyNote: event.target.value }))} value={newScoreFields.keyNote}>
                  {"CDEFGAB".split("").map((note) => <option key={note} value={note}>{note}</option>)}
                </select>
                <select aria-label={copy.accidental} onChange={(event) => setNewScoreFields((current) => ({ ...current, keyAccidental: event.target.value as NewScoreFields["keyAccidental"] }))} value={newScoreFields.keyAccidental}>
                  <option value="">{copy.natural}</option><option value="#">{copy.sharp}</option><option value="$">{copy.flat}</option>
                </select>
              </span></label>
              <label>{copy.timeSignature}<span className="field-pair">
                <input type="number" min={1} max={Number.MAX_SAFE_INTEGER} step={1} required aria-label={copy.timeNumerator}
                  onChange={(event) => setNewScoreFields((current) => ({ ...current, beatNumerator: Number(event.target.value) }))} value={newScoreFields.beatNumerator} />
                <span aria-hidden="true">/</span>
                <input type="number" min={1} max={Number.MAX_SAFE_INTEGER} step={1} required aria-label={copy.timeDenominator}
                  onChange={(event) => setNewScoreFields((current) => ({ ...current, beatDenominator: Number(event.target.value) }))} value={newScoreFields.beatDenominator} />
              </span></label>
              <label>{copy.tempo}<input onChange={(event) => setNewScoreFields((current) => ({ ...current, tempo: event.target.value }))} value={newScoreFields.tempo} /></label>
            </div>
            {dialogError && <p className="dialog-error" role="alert">{dialogError}</p>}
            <div className="dialog-actions">
              <button className="primary-button" type="submit">{copy.create}</button>
              <button onClick={() => {
                setNewScoreDraftActive(false);
                setActiveDialog(null);
                setDialogError("");
              }} type="button">{copy.cancel}</button>
            </div>
          </form>
        )}
        {activeDialog === "examples" && (
          <section>
            <h2 id="lifecycle-dialog-title">{copy.examples}</h2>
            <label className="example-search">{copy.filterExamples}
              <input autoFocus onChange={(event) => setExampleFilter(event.target.value)} type="search" value={exampleFilter} />
            </label>
            {dialogError && <p className="dialog-error" role="alert">{dialogError}</p>}
            <ul className="example-list">
              {visibleExamples.map((document) => (
                <li key={`${document.kind}:${document.name}`}>
                  <button onClick={() => { void chooseCatalogDocument(document); }} type="button">
                    <span>{document.kind === "example" ? copy.example : copy.workingCopy}</span>
                    {" · "}{document.name}
                  </button>
                </li>
              ))}
            </ul>
            {!examplesLoaded && !dialogError && <p>{copy.loadingExamples}</p>}
            {examplesLoaded && examples.length === 0 && !dialogError && <p>{copy.noExamples}</p>}
            {examples.length > 0 && visibleExamples.length === 0 && <p>{copy.noExamples}</p>}
            <div className="dialog-actions">
              <button onClick={() => { setActiveDialog(null); }} type="button">{copy.cancel}</button>
            </div>
          </section>
        )}
        {activeDialog === "reference-import" && pendingReferenceImport && (
          <section>
            <h2 id="lifecycle-dialog-title">{copy.referenceImportChoiceTitle}</h2>
            <p>{copy.referenceImportChoicePrompt(pendingReferenceImport.pages.length)}</p>
            <p>{copy.referenceImageBatch(pendingReferenceImport.pages.length)}</p>
            {dialogError && <p className="dialog-error" role="alert">{dialogError}</p>}
            <div className="dialog-actions">
              <button className="primary-button" disabled={isHandlingReferenceChoice} onClick={() => { void chooseReferenceImport("replace"); }} type="button">
                {copy.replaceReferences}
              </button>
              <button disabled={isHandlingReferenceChoice} onClick={() => { void chooseReferenceImport("cancel"); }} type="button">
                {copy.cancel}
              </button>
            </div>
          </section>
        )}
        {activeDialog === "recovery" && (
          <section>
            <h2 id="lifecycle-dialog-title">{copy.recoveryTitle}</h2>
            <p>{copy.recoveryPrompt}</p>
            {recoveryCandidate && (
              <p>{recoveryCandidate.document.name} · {copy.revision(recoveryCandidate.document.revision)}</p>
            )}
            {recoveryError && <p className="dialog-error" role="alert">{recoveryError}</p>}
            <div className="dialog-actions">
              {recoveryCandidate && (
                <button
                  className="primary-button"
                  disabled={isRecoveryActionRunning}
                  onClick={restoreRecovery}
                  type="button"
                >
                  {copy.restoreRecovery}
                </button>
              )}
              <button
                disabled={isRecoveryActionRunning}
                onClick={() => { void discardRecovery(); }}
                type="button"
              >
                {copy.discardRecovery}
              </button>
              {recoveryError && (
                <button
                  disabled={isRecoveryActionRunning}
                  onClick={continueWithoutRecovery}
                  type="button"
                >
                  {copy.continueWithoutRecovery}
                </button>
              )}
            </div>
          </section>
        )}
      </dialog>
  );
}
