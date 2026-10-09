#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod commands;

use commands::{documents, engine, exports, help, references, transcription};
use jps_document_io::{RecoverySnapshotSequence, SelectedJpsFiles};
use jps_engine_bridge::EngineSupervisor;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
#[cfg(not(debug_assertions))]
use tauri::path::BaseDirectory;
use tauri::{AppHandle, Manager, WebviewWindow};

struct DesktopState {
    engine: Arc<Mutex<EngineSupervisor>>,
    transcription: Arc<Mutex<EngineSupervisor>>,
    transcription_jobs: Arc<transcription::TranscriptionJobs>,
    engine_shutdown: Arc<AtomicBool>,
    transcription_shutdown: Arc<AtomicBool>,
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

#[tauri::command]
async fn exit_application(
    app: AppHandle,
    state: tauri::State<'_, DesktopState>,
) -> Result<(), String> {
    let windows = app.webview_windows();
    for window in windows.values() {
        if let Err(error) = window.set_enabled(false) {
            for window in windows.values() {
                let _ = window.set_enabled(true);
            }
            return Err(format!("could not disable windows during exit: {error}"));
        }
    }
    // Signal before taking the supervisor locks so an in-flight render stops promptly.
    state.engine_shutdown.store(true, Ordering::Release);
    state.transcription_shutdown.store(true, Ordering::Release);
    let engine = Arc::clone(&state.engine);
    let transcription = Arc::clone(&state.transcription);
    let shutdown = tauri::async_runtime::spawn_blocking(move || {
        engine
            .lock()
            .unwrap_or_else(|error| error.into_inner())
            .shutdown();
        transcription
            .lock()
            .unwrap_or_else(|error| error.into_inner())
            .shutdown();
    })
    .await;
    if let Err(error) = shutdown {
        for window in windows.values() {
            let _ = window.set_enabled(true);
        }
        return Err(format!("engine shutdown failed: {error}"));
    }
    app.exit(0);
    Ok(())
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .setup(|app| {
            let engine = engine_supervisor(app.handle()).map_err(std::io::Error::other)?;
            let transcription = engine_supervisor(app.handle()).map_err(std::io::Error::other)?;
            let engine_shutdown = engine.shutdown_signal();
            let transcription_shutdown = transcription.shutdown_signal();
            app.manage(DesktopState {
                engine: Arc::new(Mutex::new(engine)),
                transcription: Arc::new(Mutex::new(transcription)),
                transcription_jobs: Arc::default(),
                engine_shutdown,
                transcription_shutdown,
            });
            let navigation_app = app.handle().clone();
            let new_window_app = app.handle().clone();
            tauri::WebviewWindowBuilder::from_config(app, &app.config().app.windows[0])?
                .enable_clipboard_access()
                .on_navigation(move |url| {
                    commands::help::handle_app_navigation(&navigation_app, url.as_str())
                })
                .on_new_window(move |url, _features| {
                    commands::help::open_app_new_window(&new_window_app, url.as_str());
                    tauri::webview::NewWindowResponse::Deny
                })
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
            exit_application,
            help::open_help_destination,
            help::save_user_manual_pdf,
            help::check_for_update,
            documents::write_recovery_snapshot
        ])
        .run(tauri::generate_context!())
        .expect("failed to run OctoPus by OctaveMelody desktop application");
}
