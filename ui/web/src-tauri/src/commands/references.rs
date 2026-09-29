use crate::DesktopState;
use jps_document_io::reference_assets::stage_reference_assets as stage_reference_asset_files;
use jps_document_io::reference_images::{
    prune_reference_images as prune_managed_reference_images, remove_reference_images,
    resolve_reference_image_paths as resolve_managed_reference_paths, StagedReferenceImage,
    MAX_REFERENCE_IMAGE_FILES,
};
use jps_document_io::reference_pdfs::StagedReferencePdf;
use jps_engine_bridge::TranscribeArgs;
use serde_json::Value;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use tauri::{AppHandle, Manager, State, WebviewWindow};
use tauri_plugin_dialog::DialogExt;

fn reference_images_directory(app: &AppHandle) -> Result<PathBuf, String> {
    app.path()
        .app_cache_dir()
        .map(|directory| directory.join("reference-images"))
        .map_err(|error| format!("could not locate image cache directory: {error}"))
}

fn staged_reference_image_values(images: Vec<StagedReferenceImage>) -> Vec<Value> {
    images
        .into_iter()
        .map(|image| {
            serde_json::json!({
                "id": image.id,
                "path": image.path.to_string_lossy(),
                "name": image.name,
                "mimeType": image.mime_type,
                "byteLength": image.byte_length,
                "width": image.width,
                "height": image.height,
                "orientation": image.orientation
            })
        })
        .collect()
}

fn staged_reference_pdf_values(pdfs: Vec<StagedReferencePdf>) -> Vec<Value> {
    pdfs.into_iter()
        .map(|pdf| {
            serde_json::json!({
                "id": pdf.id,
                "path": pdf.path.to_string_lossy(),
                "name": pdf.name,
                "byteLength": pdf.byte_length,
                "sha256": pdf.sha256
            })
        })
        .collect()
}

#[tauri::command]
pub(crate) async fn stage_reference_assets(
    app: AppHandle,
    window: WebviewWindow,
    paths: Option<Vec<String>>,
    suggested_path: Option<String>,
) -> Result<Option<Value>, String> {
    let selected_paths = match paths {
        Some(paths) => Some(paths.into_iter().map(PathBuf::from).collect()),
        None => tauri::async_runtime::spawn_blocking(move || {
            let mut picker = window.dialog().file().set_parent(&window).add_filter(
                "PNG, JPEG, or PDF reference",
                &["png", "jpg", "jpeg", "pdf"],
            );
            if let Some(directory) = suggested_path
                .and_then(|path| Path::new(&path).parent().map(Path::to_path_buf))
                .filter(|directory| directory.is_dir())
            {
                picker = picker.set_directory(directory);
            }
            picker
                .blocking_pick_file()
                .map(|path| {
                    path.into_path()
                        .map_err(|_| "native dialog did not return a local path".to_owned())
                })
                .transpose()
                .map(|path| path.map(|path| vec![path]))
        })
        .await
        .map_err(|error| format!("reference picker task failed: {error}"))??,
    };
    let Some(paths) = selected_paths.filter(|paths| !paths.is_empty()) else {
        return Ok(None);
    };
    let directory = reference_images_directory(&app)?;
    tauri::async_runtime::spawn_blocking(move || {
        let staged =
            stage_reference_asset_files(&paths, &directory).map_err(|error| error.to_string())?;
        Ok(Some(serde_json::json!({
            "images": staged_reference_image_values(staged.images),
            "pdfs": staged_reference_pdf_values(staged.pdfs),
            "order": staged.order,
        })))
    })
    .await
    .map_err(|error| format!("reference import task failed: {error}"))?
}

#[tauri::command]
pub(crate) async fn discard_reference_images(
    app: AppHandle,
    ids: Vec<String>,
) -> Result<(), String> {
    if ids.len() > MAX_REFERENCE_IMAGE_FILES {
        return Err("too many image IDs".into());
    }
    let directory = reference_images_directory(&app)?;
    tauri::async_runtime::spawn_blocking(move || {
        remove_reference_images(&directory, &ids).map_err(|error| error.to_string())
    })
    .await
    .map_err(|error| format!("image cleanup task failed: {error}"))?
}

#[tauri::command]
pub(crate) async fn prune_reference_images(
    app: AppHandle,
    retained_ids: Vec<String>,
) -> Result<(), String> {
    if retained_ids.len() > MAX_REFERENCE_IMAGE_FILES {
        return Err("too many image IDs".into());
    }
    let directory = reference_images_directory(&app)?;
    tauri::async_runtime::spawn_blocking(move || {
        prune_managed_reference_images(&directory, &retained_ids).map_err(|error| error.to_string())
    })
    .await
    .map_err(|error| format!("image cleanup task failed: {error}"))?
}

#[tauri::command]
pub(crate) async fn resolve_reference_images(
    app: AppHandle,
    ids: Vec<String>,
) -> Result<Vec<Value>, String> {
    let directory = reference_images_directory(&app)?;
    tauri::async_runtime::spawn_blocking(move || {
        resolve_managed_reference_paths(&directory, &ids)
            .map(|images| {
                images
                    .into_iter()
                    .map(|(id, path)| serde_json::json!({ "id": id, "path": path.to_string_lossy() }))
                    .collect()
            })
            .map_err(|error| error.to_string())
    })
    .await
    .map_err(|error| format!("image restore task failed: {error}"))?
}

#[tauri::command]
pub(crate) async fn transcribe_reference(
    app: AppHandle,
    state: State<'_, DesktopState>,
    asset_id: String,
    document_id: String,
    document_revision: u64,
) -> Result<Value, String> {
    let directory = reference_images_directory(&app)?;
    let supervisor = Arc::clone(&state.transcription);
    tauri::async_runtime::spawn_blocking(move || {
        let paths = resolve_managed_reference_paths(&directory, &[asset_id])
            .map_err(|error| error.to_string())?;
        let path = paths
            .into_iter()
            .next()
            .ok_or("selected reference file is unavailable")?
            .1;
        let path = path
            .to_str()
            .ok_or("managed reference path is not UTF-8")?
            .to_owned();
        let args = TranscribeArgs {
            document_id,
            document_revision,
            path,
        };
        supervisor
            .lock()
            .map_err(|_| "engine lock poisoned".to_owned())?
            .transcribe(args)
    })
    .await
    .map_err(|error| format!("transcription task failed: {error}"))?
}
