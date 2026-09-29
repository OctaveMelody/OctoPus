use crate::DesktopState;
use jps_document_io::file_exports::{publish_export_pages, ExportFormat};
use jps_document_io::score_exports::{export_jpg_pages, export_pdf};
use jps_document_io::svg_exports::publish_svg_pages;
use jps_engine_bridge::RenderArgs;
use serde_json::Value;
use std::fs;
use std::io;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use tauri::{AppHandle, Manager, State, WebviewWindow};
use tauri_plugin_dialog::DialogExt;

fn export_svg_pages(
    response: Value,
    document_id: &str,
    revision: u64,
) -> Result<(Vec<String>, bool), String> {
    if response["status"] != "ok" {
        return Err(response["error"]["message"]
            .as_str()
            .unwrap_or("SVG rendering failed")
            .to_owned());
    }
    if response["document_id"].as_str() != Some(document_id)
        || response["document_revision"].as_u64() != Some(revision)
    {
        return Err("SVG export response identity mismatch".into());
    }
    let result = response
        .get("result")
        .ok_or("SVG export response has no result")?;
    let page_values = result["pages"]
        .as_array()
        .ok_or("SVG export response has invalid pages")?;
    let pages = page_values
        .iter()
        .map(|page| {
            page.as_str()
                .map(str::to_owned)
                .ok_or_else(|| "SVG export response has invalid pages".to_owned())
        })
        .collect::<Result<Vec<_>, _>>()?;
    if pages.is_empty() || result["page_count"].as_u64() != Some(pages.len() as u64) {
        return Err("SVG export response has inconsistent page count".into());
    }
    let custom_markup_omitted = result["custom_markup_omitted"]
        .as_bool()
        .ok_or("SVG export response has invalid custom-markup status")?;
    Ok((pages, custom_markup_omitted))
}

fn export_extension(format: ExportFormat) -> &'static str {
    match format {
        ExportFormat::Svg => "svg",
        ExportFormat::Pdf => "pdf",
        ExportFormat::Jpg => "jpg",
    }
}

fn export_filter(format: ExportFormat) -> &'static str {
    match format {
        ExportFormat::Svg => "SVG image",
        ExportFormat::Pdf => "PDF document",
        ExportFormat::Jpg => "JPG image",
    }
}

async fn choose_export_path(
    app: AppHandle,
    window: WebviewWindow,
    suggested_path: Option<String>,
    suggested_name: Option<String>,
    format: ExportFormat,
) -> Result<Option<(PathBuf, bool)>, String> {
    let source_path = suggested_path
        .map(PathBuf::from)
        .filter(|path| path.is_absolute());
    let initial_directory = source_path
        .as_ref()
        .and_then(|path| path.parent().filter(|directory| directory.is_dir()))
        .map(Path::to_path_buf)
        .or_else(|| {
            app.path()
                .document_dir()
                .ok()
                .filter(|directory| directory.is_dir())
        })
        .or_else(|| {
            app.path()
                .home_dir()
                .ok()
                .filter(|directory| directory.is_dir())
        })
        .ok_or("could not locate Documents or home directory")?;
    let candidate_name = source_path
        .as_ref()
        .and_then(|path| path.file_stem())
        .map(|stem| stem.to_string_lossy().into_owned())
        .or_else(|| {
            suggested_name.filter(|name| {
                !name.trim().is_empty()
                    && name.len() <= 255
                    && !name
                        .chars()
                        .any(|character| matches!(character, '/' | '\\' | '\0'))
            })
        })
        .unwrap_or_else(|| "Untitled".into());
    let stem = Path::new(&candidate_name).file_stem().map_or_else(
        || "Untitled".into(),
        |value| value.to_string_lossy().into_owned(),
    );
    let file_name = format!("{stem}.{}", export_extension(format));
    let selected = tauri::async_runtime::spawn_blocking(move || {
        window
            .dialog()
            .file()
            .set_parent(&window)
            .add_filter(export_filter(format), &[export_extension(format)])
            .set_directory(initial_directory)
            .set_file_name(file_name)
            .blocking_save_file()
            .map(|path| {
                path.into_path()
                    .map_err(|_| "native dialog did not return a local path".to_owned())
            })
            .transpose()
    })
    .await
    .map_err(|error| format!("{} save dialog failed: {error}", export_filter(format)))??;
    let Some(mut selected_path) = selected else {
        return Ok(None);
    };
    if selected_path.extension().is_none() {
        selected_path.set_extension(export_extension(format));
    }
    if !selected_path
        .extension()
        .and_then(|extension| extension.to_str())
        .is_some_and(|extension| extension.eq_ignore_ascii_case(export_extension(format)))
    {
        return Err(format!(
            "export destination must use the .{} extension",
            export_extension(format)
        ));
    }
    let replace_existing = match fs::symlink_metadata(&selected_path) {
        Ok(_) => true,
        Err(error) if error.kind() == io::ErrorKind::NotFound => false,
        Err(error) => return Err(format!("could not inspect export destination: {error}")),
    };
    Ok(Some((selected_path, replace_existing)))
}

#[tauri::command]
pub(crate) async fn export_svg(
    app: AppHandle,
    window: WebviewWindow,
    state: State<'_, DesktopState>,
    args: RenderArgs,
    suggested_path: Option<String>,
    suggested_name: Option<String>,
) -> Result<Option<Value>, String> {
    let Some((selected_path, replace_existing)) = choose_export_path(
        app,
        window,
        suggested_path,
        suggested_name,
        ExportFormat::Svg,
    )
    .await?
    else {
        return Ok(None);
    };

    let document_id = args.document_id.clone();
    let revision = args.document_revision;
    let supervisor = Arc::clone(&state.engine);
    tauri::async_runtime::spawn_blocking(move || {
        let response = supervisor
            .lock()
            .map_err(|_| "engine lock poisoned".to_owned())?
            .export_svg(args)?;
        let (pages, custom_markup_omitted) = export_svg_pages(response, &document_id, revision)?;
        let outputs = publish_svg_pages(&selected_path, &pages, replace_existing)
            .map_err(|error| error.to_string())?;
        let filenames = outputs
            .iter()
            .map(|path| {
                path.file_name()
                    .map(|name| name.to_string_lossy().into_owned())
                    .ok_or("SVG export path has no filename")
            })
            .collect::<Result<Vec<_>, _>>()?;
        Ok(Some(serde_json::json!({
            "documentId": document_id,
            "revision": revision,
            "pageCount": pages.len(),
            "filenames": filenames,
            "customMarkupOmitted": custom_markup_omitted
        })))
    })
    .await
    .map_err(|error| format!("SVG export task failed: {error}"))?
}

// Tauri injects the app, window and engine state; the remaining parameters are the IPC payload.
#[allow(clippy::too_many_arguments)]
#[tauri::command]
pub(crate) async fn export_score(
    app: AppHandle,
    window: WebviewWindow,
    state: State<'_, DesktopState>,
    args: RenderArgs,
    suggested_path: Option<String>,
    suggested_name: Option<String>,
    format: String,
    dpi: Option<u16>,
) -> Result<Option<Value>, String> {
    let (format, dpi) = match format.as_str() {
        "pdf" if dpi.is_none() => (ExportFormat::Pdf, None),
        "jpg" => {
            let dpi = dpi.unwrap_or(96);
            if !matches!(dpi, 96 | 300) {
                return Err("JPG resolution must be 96 or 300 DPI".into());
            }
            (ExportFormat::Jpg, Some(dpi))
        }
        "pdf" => return Err("PDF export does not accept a JPG resolution".into()),
        _ => return Err("export format must be PDF or JPG".into()),
    };
    let Some((selected_path, replace_existing)) =
        choose_export_path(app, window, suggested_path, suggested_name, format).await?
    else {
        return Ok(None);
    };

    let document_id = args.document_id.clone();
    let revision = args.document_revision;
    let supervisor = Arc::clone(&state.engine);
    tauri::async_runtime::spawn_blocking(move || {
        let response = supervisor
            .lock()
            .map_err(|_| "engine lock poisoned".to_owned())?
            .export_svg(args)?;
        let (svg_pages, custom_markup_omitted) =
            export_svg_pages(response, &document_id, revision)?;
        let output_pages = match format {
            ExportFormat::Pdf => vec![export_pdf(&svg_pages).map_err(|error| error.to_string())?],
            ExportFormat::Jpg => export_jpg_pages(&svg_pages, dpi.unwrap_or(96))
                .map_err(|error| error.to_string())?,
            ExportFormat::Svg => return Err("SVG uses the SVG export command".into()),
        };
        let output_bytes = output_pages.iter().map(Vec::as_slice).collect::<Vec<_>>();
        let outputs = publish_export_pages(&selected_path, format, &output_bytes, replace_existing)
            .map_err(|error| error.to_string())?;
        let filenames = outputs
            .iter()
            .map(|path| {
                path.file_name()
                    .map(|name| name.to_string_lossy().into_owned())
                    .ok_or("export path has no filename")
            })
            .collect::<Result<Vec<_>, _>>()?;
        Ok(Some(serde_json::json!({
            "documentId": document_id,
            "revision": revision,
            "format": match format {
                ExportFormat::Pdf => "pdf",
                ExportFormat::Jpg => "jpg",
                ExportFormat::Svg => "svg",
            },
            "dpi": dpi,
            "pageCount": svg_pages.len(),
            "filenames": filenames,
            "customMarkupOmitted": custom_markup_omitted
        })))
    })
    .await
    .map_err(|error| format!("score export task failed: {error}"))?
}
