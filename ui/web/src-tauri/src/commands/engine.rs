use crate::DesktopState;
use jps_engine_bridge::{LoadDocumentArgs, RenderArgs, RenderPageArgs, SerializeDocumentArgs};
use serde_json::Value;
use std::sync::Arc;
use tauri::State;

fn capability_summary(capabilities: Value) -> Value {
    serde_json::json!({
        "ocr": capabilities["ocr"].as_bool().unwrap_or(false),
        "png_export": capabilities["png_export"].as_bool().unwrap_or(false),
        "fonts": capabilities["fonts"],
        "font_policy": capabilities["font_policy"].as_str().unwrap_or("reference"),
        "font_platform": capabilities["font_platform"].as_str().unwrap_or("other"),
    })
}

#[tauri::command]
pub(crate) async fn parse_score(
    state: State<'_, DesktopState>,
    args: RenderArgs,
) -> Result<Value, String> {
    let supervisor = Arc::clone(&state.engine);
    tauri::async_runtime::spawn_blocking(move || {
        supervisor
            .lock()
            .map_err(|_| "engine lock poisoned")?
            .parse(args)
    })
    .await
    .map_err(|error| format!("parse task failed: {error}"))?
}

#[tauri::command]
pub(crate) async fn render_score(
    state: State<'_, DesktopState>,
    args: RenderArgs,
) -> Result<Value, String> {
    let supervisor = Arc::clone(&state.engine);
    tauri::async_runtime::spawn_blocking(move || {
        let mut supervisor = supervisor.lock().map_err(|_| "engine lock poisoned")?;
        supervisor.render(args)
    })
    .await
    .map_err(|error| format!("render task failed: {error}"))?
}

#[tauri::command]
pub(crate) async fn render_score_page(
    state: State<'_, DesktopState>,
    args: RenderPageArgs,
) -> Result<Value, String> {
    let supervisor = Arc::clone(&state.engine);
    tauri::async_runtime::spawn_blocking(move || {
        let mut supervisor = supervisor.lock().map_err(|_| "engine lock poisoned")?;
        supervisor.render_page(args)
    })
    .await
    .map_err(|error| format!("page render task failed: {error}"))?
}

#[tauri::command]
pub(crate) async fn load_document(
    state: State<'_, DesktopState>,
    args: LoadDocumentArgs,
) -> Result<Value, String> {
    let supervisor = Arc::clone(&state.engine);
    tauri::async_runtime::spawn_blocking(move || {
        let mut supervisor = supervisor.lock().map_err(|_| "engine lock poisoned")?;
        supervisor.load_document(args)
    })
    .await
    .map_err(|error| format!("document load task failed: {error}"))?
}

#[tauri::command]
pub(crate) async fn serialize_document(
    state: State<'_, DesktopState>,
    args: SerializeDocumentArgs,
) -> Result<Value, String> {
    let supervisor = Arc::clone(&state.engine);
    tauri::async_runtime::spawn_blocking(move || {
        let mut supervisor = supervisor.lock().map_err(|_| "engine lock poisoned")?;
        supervisor.serialize_document(args)
    })
    .await
    .map_err(|error| format!("document serialize task failed: {error}"))?
}

#[tauri::command]
pub(crate) async fn get_engine_capabilities(
    state: State<'_, DesktopState>,
) -> Result<Value, String> {
    let supervisor = Arc::clone(&state.engine);
    tauri::async_runtime::spawn_blocking(move || {
        let capabilities = supervisor
            .lock()
            .map_err(|_| "engine lock poisoned".to_owned())?
            .capabilities()?;
        Ok(capability_summary(capabilities))
    })
    .await
    .map_err(|error| format!("engine capability query failed: {error}"))?
}

#[tauri::command]
pub(crate) async fn refresh_engine_capabilities(
    state: State<'_, DesktopState>,
) -> Result<Value, String> {
    let supervisor = Arc::clone(&state.engine);
    tauri::async_runtime::spawn_blocking(move || {
        let capabilities = supervisor
            .lock()
            .map_err(|_| "engine lock poisoned".to_owned())?
            .refresh_capabilities()?;
        Ok(capability_summary(capabilities))
    })
    .await
    .map_err(|error| format!("engine font refresh failed: {error}"))?
}
