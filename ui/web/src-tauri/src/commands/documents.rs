use jps_document_io::reference_recovery::validate_recovery_references;
use jps_document_io::{
    list_jps_examples as get_jps_examples, read_jps_example, read_jps_text,
    read_recovery_snapshot as read_recovery_text, validate_jps_path, write_jps_text_atomically,
    write_jps_text_atomically_if_unchanged, RecoverySnapshotSequence, SelectedJpsFiles,
    MAX_JPS_FILE_BYTES, MAX_RECOVERY_SNAPSHOT_BYTES,
};
use serde_json::Value;
use std::path::{Path, PathBuf};
#[cfg(not(debug_assertions))]
use tauri::path::BaseDirectory;
use tauri::{AppHandle, Manager, State, WebviewWindow};
use tauri_plugin_dialog::DialogExt;

#[cfg(debug_assertions)]
fn examples_directory(_app: &AppHandle) -> Result<PathBuf, String> {
    Ok(Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../samples/jps_files"))
}

#[cfg(not(debug_assertions))]
fn examples_directory(app: &AppHandle) -> Result<PathBuf, String> {
    app.path()
        .resolve(
            crate::resource_relative("examples"),
            BaseDirectory::Resource,
        )
        .map_err(|error| format!("could not locate bundled JPS examples: {error}"))
}

fn working_copies_directory(app: &AppHandle) -> Result<PathBuf, String> {
    app.path()
        .app_data_dir()
        .map(|directory| directory.join("working-copies"))
        .map_err(|error| format!("could not locate app data directory: {error}"))
}

fn recovery_snapshot_path(app: &AppHandle) -> Result<PathBuf, String> {
    app.path()
        .app_data_dir()
        .map(|directory| directory.join("recovery.json"))
        .map_err(|error| format!("could not locate app data directory: {error}"))
}

#[tauri::command]
pub(crate) async fn read_recovery_snapshot(app: AppHandle) -> Result<Option<String>, String> {
    let path = recovery_snapshot_path(&app)?;
    tauri::async_runtime::spawn_blocking(move || {
        read_recovery_text(&path).map_err(|error| error.to_string())
    })
    .await
    .map_err(|error| format!("recovery read task failed: {error}"))?
}

#[tauri::command]
pub(crate) async fn write_recovery_snapshot(
    app: AppHandle,
    recovery_sequence: State<'_, RecoverySnapshotSequence>,
    sequence: u64,
    text: Option<String>,
) -> Result<bool, String> {
    if sequence == 0 || sequence > 9_007_199_254_740_991 {
        return Err("recovery sequence is invalid".into());
    }
    if let Some(snapshot) = &text {
        if snapshot.len() > MAX_RECOVERY_SNAPSHOT_BYTES {
            return Err("recovery snapshot exceeds the size limit".into());
        }
        let value: Value = serde_json::from_str(snapshot)
            .map_err(|error| format!("recovery snapshot is invalid JSON: {error}"))?;
        if !value.is_object()
            || !matches!(value.get("version").and_then(Value::as_u64), Some(1..=4))
            || !value.get("document").is_some_and(Value::is_object)
            || !value
                .get("draft")
                .is_some_and(|draft| draft.is_null() || draft.is_object())
        {
            return Err("recovery snapshot version is unsupported".into());
        }
    }
    validate_recovery_references(text.as_deref())?;

    let path = recovery_snapshot_path(&app)?;
    let sequence_state = recovery_sequence.inner().clone();
    tauri::async_runtime::spawn_blocking(move || {
        sequence_state
            .write_if_newer(&path, sequence, text.as_deref())
            .map_err(|error| error.to_string())
    })
    .await
    .map_err(|error| format!("recovery write task failed: {error}"))?
}

#[tauri::command]
pub(crate) async fn open_jps_file(
    window: WebviewWindow,
    selected_files: State<'_, SelectedJpsFiles>,
    initial_path: Option<String>,
) -> Result<Option<Value>, String> {
    let selected = tauri::async_runtime::spawn_blocking(move || {
        let mut dialog = window.dialog().file().set_parent(&window);
        if let Some(directory) = initial_path
            .and_then(|path| Path::new(&path).parent().map(Path::to_path_buf))
            .filter(|directory| directory.is_dir())
        {
            dialog = dialog.set_directory(directory);
        }
        dialog
            .add_filter("Jianpu source", &["jps"])
            .blocking_pick_file()
    })
    .await
    .map_err(|error| format!("JPS open dialog failed: {error}"))?;
    let Some(selected) = selected else {
        return Ok(None);
    };
    let source_path = selected
        .into_path()
        .map_err(|_| "native dialog did not return a local file path".to_owned())?;
    let source_path = validate_jps_path(&source_path).map_err(|error| error.to_string())?;
    let read_path = source_path.clone();
    let text = tauri::async_runtime::spawn_blocking(move || {
        read_jps_text(&read_path).map_err(|error| error.to_string())
    })
    .await
    .map_err(|error| format!("JPS read task failed: {error}"))??;
    let name = source_path
        .file_name()
        .map(|name| name.to_string_lossy().into_owned())
        .ok_or_else(|| "file path must name a file".to_owned())?;
    selected_files.remember(source_path.clone())?;
    Ok(Some(serde_json::json!({
        "name": name,
        "path": source_path.to_string_lossy(),
        "suggestedPath": source_path.to_string_lossy(),
        "text": text
    })))
}

#[tauri::command]
pub(crate) async fn list_jps_documents(app: AppHandle) -> Result<Value, String> {
    let examples = examples_directory(&app)?;
    let working_copies = working_copies_directory(&app)?;
    tauri::async_runtime::spawn_blocking(move || {
        let mut documents: Vec<Value> = get_jps_examples(&examples)
            .map_err(|error| error.to_string())?
            .into_iter()
            .map(|name| serde_json::json!({ "name": name, "kind": "example" }))
            .collect();
        if working_copies.is_dir() {
            documents.extend(
                get_jps_examples(&working_copies)
                    .map_err(|error| error.to_string())?
                    .into_iter()
                    .map(|name| serde_json::json!({ "name": name, "kind": "working-copy" })),
            );
        }
        Ok(Value::Array(documents))
    })
    .await
    .map_err(|error| format!("JPS document list task failed: {error}"))?
}

#[tauri::command]
pub(crate) async fn open_jps_catalog_document(
    app: AppHandle,
    selected_files: State<'_, SelectedJpsFiles>,
    kind: String,
    name: String,
) -> Result<Value, String> {
    let directory = match kind.as_str() {
        "example" => examples_directory(&app)?,
        "working-copy" => working_copies_directory(&app)?,
        _ => return Err("unknown JPS catalog entry kind".into()),
    };
    let is_working_copy = kind == "working-copy";
    let (name, text, path) = tauri::async_runtime::spawn_blocking(move || {
        let text = read_jps_example(&directory, &name).map_err(|error| error.to_string())?;
        let path = if is_working_copy {
            let path =
                validate_jps_path(&directory.join(&name)).map_err(|error| error.to_string())?;
            Some(path)
        } else {
            None
        };
        Ok::<_, String>((name, text, path))
    })
    .await
    .map_err(|error| format!("JPS catalog read task failed: {error}"))??;
    if let Some(path) = &path {
        selected_files.remember(path.clone())?;
    }
    let path = path.map(|path| path.to_string_lossy().into_owned());
    let suggested_path = path.clone();
    Ok(serde_json::json!({
        "name": name,
        "path": path,
        "suggestedPath": suggested_path,
        "text": text
    }))
}

// Tauri injects the window and managed state; these parameters mirror the stable IPC payload.
#[allow(clippy::too_many_arguments)]
#[tauri::command]
pub(crate) async fn save_jps_file(
    window: WebviewWindow,
    selected_files: State<'_, SelectedJpsFiles>,
    path: Option<String>,
    suggested_path: Option<String>,
    suggested_name: Option<String>,
    recent_saved_path: Option<String>,
    expected_text: Option<String>,
    text: String,
    save_as: bool,
) -> Result<Option<String>, String> {
    if text.len() > MAX_JPS_FILE_BYTES {
        return Err(format!(
            "JPS source exceeds the {MAX_JPS_FILE_BYTES}-byte limit"
        ));
    }

    if path.is_some() && !save_as && expected_text.is_none() {
        return Err("the saved file snapshot is required for a direct save".into());
    }

    let (target, expected_path) = if let Some(path) = path.filter(|_| !save_as) {
        let path = validate_jps_path(Path::new(&path)).map_err(|error| error.to_string())?;
        if !selected_files.allows(&path)? {
            return Err("save path was not selected in this app session".into());
        }
        (path.clone(), Some(path))
    } else {
        let suggested = match suggested_path {
            Some(path) => {
                let path =
                    validate_jps_path(Path::new(&path)).map_err(|error| error.to_string())?;
                Some(path)
            }
            None => None,
        };
        let expected_path = suggested.clone();
        let selected = tauri::async_runtime::spawn_blocking(move || {
            let dialog = window
                .dialog()
                .file()
                .set_parent(&window)
                .add_filter("Jianpu source", &["jps"]);
            let initial_directory = recent_saved_path
                .as_deref()
                .and_then(|path| Path::new(path).parent().map(Path::to_path_buf))
                .filter(|directory| directory.is_dir())
                .or_else(|| {
                    suggested
                        .as_ref()
                        .and_then(|path| path.parent())
                        .filter(|directory| directory.is_dir())
                        .map(Path::to_path_buf)
                });
            let file_name = suggested_name
                .filter(|name| {
                    !name.trim().is_empty()
                        && name.len() <= 255
                        && !name
                            .chars()
                            .any(|character| matches!(character, '/' | '\\' | '\0'))
                })
                .or_else(|| {
                    suggested.as_ref().and_then(|path| {
                        path.file_name()
                            .map(|name| name.to_string_lossy().into_owned())
                    })
                })
                .unwrap_or_else(|| "Untitled.jps".into());
            let dialog = match initial_directory {
                Some(directory) => dialog.set_directory(directory).set_file_name(file_name),
                None => dialog.set_file_name(file_name),
            };
            dialog.blocking_save_file()
        })
        .await
        .map_err(|error| format!("JPS save dialog failed: {error}"))?;
        let Some(selected) = selected else {
            return Ok(None);
        };
        let mut path = selected
            .into_path()
            .map_err(|_| "native dialog did not return a local file path".to_owned())?;
        if path.extension().is_none() {
            path.set_extension("jps");
        }
        (
            validate_jps_path(&path).map_err(|error| error.to_string())?,
            expected_path,
        )
    };

    let write_path = target.clone();
    let expected = expected_text.filter(|_| expected_path.as_deref() == Some(target.as_path()));
    tauri::async_runtime::spawn_blocking(move || {
        let result = match expected.as_deref() {
            Some(expected_text) => {
                write_jps_text_atomically_if_unchanged(&write_path, expected_text, &text)
            }
            None => write_jps_text_atomically(&write_path, &text),
        };
        result.map_err(|error| error.to_string())
    })
    .await
    .map_err(|error| format!("JPS write task failed: {error}"))??;
    selected_files.remember(target.clone())?;
    Ok(Some(target.to_string_lossy().into_owned()))
}
