//! One cancellable transcription session, independent of the preview worker.
use crate::DesktopState;
use jps_document_io::reference_images::resolve_reference_image_paths;
use jps_engine_bridge::TranscribeArgs;
use serde_json::{json, Value};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use tauri::{Emitter, Manager, State, WebviewWindow};

use jps_engine_bridge::transcription_jobs::JobKey;
pub(crate) use jps_engine_bridge::transcription_jobs::TranscriptionJobs;

struct JobGuard {
    jobs: Arc<TranscriptionJobs>,
    key: JobKey,
    cancelled: Arc<AtomicBool>,
}
impl Drop for JobGuard {
    fn drop(&mut self) {
        self.jobs.finish(&self.key, &self.cancelled);
    }
}

#[tauri::command]
pub(crate) fn cancel_transcription(
    state: State<'_, DesktopState>,
    job_id: String,
    document_id: String,
    document_revision: u64,
) -> Result<bool, String> {
    state.transcription_jobs.cancel(JobKey {
        id: job_id,
        document_id,
        revision: document_revision,
    })
}

#[tauri::command]
pub(crate) async fn transcribe_reference(
    window: WebviewWindow,
    state: State<'_, DesktopState>,
    asset_id: String,
    document_id: String,
    document_revision: u64,
    job_id: String,
) -> Result<Value, String> {
    let key = JobKey {
        id: job_id.clone(),
        document_id: document_id.clone(),
        revision: document_revision,
    };
    let jobs = Arc::clone(&state.transcription_jobs);
    // Register before filesystem work; an earlier cancellation prevents worker startup.
    let cancelled = jobs.register(key.clone())?;
    let guard = JobGuard {
        jobs,
        key,
        cancelled: Arc::clone(&cancelled),
    };
    let directory = super::references::reference_images_directory(window.app_handle())?;
    let supervisor = Arc::clone(&state.transcription);
    tauri::async_runtime::spawn_blocking(move || {
        let _guard = guard;
        if cancelled.load(Ordering::Acquire) {
            return Err("transcription cancelled".into());
        }
        let paths = resolve_reference_image_paths(&directory, &[asset_id])
            .map_err(|error| error.to_string())?;
        let path = paths
            .into_iter()
            .next()
            .ok_or("selected reference file is unavailable")?
            .1;
        let args = TranscribeArgs {
            document_id: document_id.clone(),
            document_revision,
            path: path
                .to_str()
                .ok_or("managed reference path is not UTF-8")?
                .to_owned(),
        };
        supervisor
            .lock()
            .map_err(|_| "engine lock poisoned")?
            .transcribe_with_progress(args, cancelled, move |progress| {
                let _ = window.emit(
                    "octopus-transcription-progress",
                    json!({
                        "jobId": job_id, "documentId": document_id, "revision": document_revision,
                        "progress": progress,
                    }),
                );
            })
    })
    .await
    .map_err(|error| format!("transcription task failed: {error}"))?
}
