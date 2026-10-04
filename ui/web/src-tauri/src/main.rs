#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod commands;

use commands::{documents, engine, exports, help, references, transcription};
use jps_document_io::{RecoverySnapshotSequence, SelectedJpsFiles};
use jps_engine_bridge::EngineSupervisor;
use std::sync::{Arc, Mutex};
#[cfg(not(debug_assertions))]
use tauri::path::BaseDirectory;
use tauri::{AppHandle, Manager, WebviewWindow};

struct DesktopState {
    engine: Arc<Mutex<EngineSupervisor>>,
    transcription: Arc<Mutex<EngineSupervisor>>,
    transcription_jobs: Arc<transcription::TranscriptionJobs>,
}

#[cfg(debug_assertions)]
fn engine_supervisor(_app: &AppHandle) -> Result<EngineSupervisor, String> {
    Ok(EngineSupervisor::default())
}

#[cfg(not(debug_assertions))]
fn engine_supervisor(app: &AppHandle) -> Result<EngineSupervisor, String> {
    let executable = if cfg!(windows) {
        "engine/octopus-engine.exe"
    } else {
        "engine/octopus-engine"
    };
    let path = app
        .path()
        .resolve(resource_relative(executable), BaseDirectory::Resource)
        .map_err(|error| format!("could not locate bundled Python engine: {error}"))?;
    Ok(EngineSupervisor::packaged(path))
}

#[cfg(not(debug_assertions))]
fn resource_relative(path: &str) -> String {
    if cfg!(target_os = "linux") {
        path.to_owned()
    } else {
        format!("lib/OctoPus/{path}")
    }
}

#[tauri::command]
fn font_directory(app: AppHandle) -> Result<String, String> {
    #[cfg(debug_assertions)]
    let path =
        std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../src/octopus/assets/fonts");
    #[cfg(not(debug_assertions))]
    let path = app
        .path()
        .resolve(resource_relative("fonts"), BaseDirectory::Resource)
        .map_err(|error| error.to_string())?;
    let path = path.canonicalize().map_err(|error| error.to_string())?;
    app.asset_protocol_scope()
        .allow_directory(&path, true)
        .map_err(|error| error.to_string())?;
    Ok(path.to_string_lossy().into_owned())
}

#[tauri::command]
fn toggle_window_maximize(window: WebviewWindow) {
    if window.is_maximized().unwrap_or(false) {
        let _ = window.unmaximize();
    } else {
        let _ = window.maximize();
    }
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .setup(|app| {
            let engine = engine_supervisor(app.handle()).map_err(std::io::Error::other)?;
            let transcription = engine_supervisor(app.handle()).map_err(std::io::Error::other)?;
            app.manage(DesktopState {
                engine: Arc::new(Mutex::new(engine)),
                transcription: Arc::new(Mutex::new(transcription)),
                transcription_jobs: Arc::default(),
            });
            tauri::WebviewWindowBuilder::from_config(app, &app.config().app.windows[0])?
                .enable_clipboard_access()
                .build()?;
            Ok(())
        })
        .manage(SelectedJpsFiles::default())
        .manage(RecoverySnapshotSequence::default())
        .invoke_handler(tauri::generate_handler![
            font_directory,
            references::discard_reference_images,
            exports::export_score,
            exports::export_svg,
            engine::get_engine_capabilities,
            documents::list_jps_documents,
            engine::load_document,
            documents::open_jps_file,
            documents::open_recent_jps_file,
            documents::open_jps_catalog_document,
            documents::read_recovery_snapshot,
            references::prune_reference_images,
            references::resolve_reference_images,
            engine::parse_score,
            engine::render_score,
            engine::render_score_page,
            engine::serialize_document,
            documents::save_jps_file,
            references::stage_reference_assets,
            transcription::transcribe_reference,
            transcription::cancel_transcription,
            toggle_window_maximize,
            help::open_help_destination,
            help::check_for_update,
            documents::write_recovery_snapshot
        ])
        .run(tauri::generate_context!())
        .expect("failed to run OctoPus by OctaveMelody desktop application");
}
