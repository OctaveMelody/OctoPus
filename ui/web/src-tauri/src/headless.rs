//! JSON command operations used by external OctoPus skills.

mod args;
mod files;
mod worker;

use args::{
    has_extension, parse_options, require_one_operand, resolve_input_path,
    resolve_output_directory, resolve_output_path, CliOptions,
};
use files::{ensure_parent, publish_new_files, reject_existing_outputs};
use jps_document_io::file_exports::{publish_export_pages, ExportFormat};
use jps_document_io::score_exports::{export_jpg_pages, export_pdf, export_png_pages};
use jps_document_io::svg_exports::publish_svg_pages;
use jps_engine_bridge::{EngineSupervisor, LoadDocumentArgs, RenderArgs, TranscribeArgs};
use serde_json::{json, Value};
use std::fs;
use std::io::{self, Write};
use std::path::{Path, PathBuf};
use worker::{engine_supervisor, executable_on_path, format_extension, path_string};

const CLI_SCHEMA_VERSION: &str = "1.0.0";
const HEADLESS_DOCUMENT_ID: &str = "octopus-headless";

#[derive(Debug, Clone, Copy)]
enum FailureKind {
    Usage,
    Input,
    Capability,
    Conflict,
    Execution,
}

#[derive(Debug)]
pub(super) struct CliFailure {
    kind: FailureKind,
    code: String,
    message: String,
    conflict: Option<Value>,
}

impl CliFailure {
    pub(super) fn usage(message: impl Into<String>) -> Self {
        Self::new(FailureKind::Usage, "invalid_arguments", message)
    }

    pub(super) fn input(code: impl Into<String>, message: impl Into<String>) -> Self {
        Self::new(FailureKind::Input, code, message)
    }

    pub(super) fn capability(code: impl Into<String>, message: impl Into<String>) -> Self {
        Self::new(FailureKind::Capability, code, message)
    }

    pub(super) fn execution(code: impl Into<String>, message: impl Into<String>) -> Self {
        Self::new(FailureKind::Execution, code, message)
    }

    fn new(kind: FailureKind, code: impl Into<String>, message: impl Into<String>) -> Self {
        Self {
            kind,
            code: code.into(),
            message: message.into(),
            conflict: None,
        }
    }

    fn session(error: crate::session::SessionError) -> Self {
        match error {
            crate::session::SessionError::Conflict(conflict) => Self {
                kind: FailureKind::Conflict,
                code: "active_session_conflict".into(),
                message:
                    "Close the conflicting OctoPus document and retry, or cancel the headless job."
                        .into(),
                conflict: Some(
                    serde_json::to_value(conflict)
                        .unwrap_or_else(|_| json!({ "path": null, "sessions": [] })),
                ),
            },
            error => Self::input("input_read_failed", error.to_string()),
        }
    }

    fn exit_code(&self) -> i32 {
        match self.kind {
            FailureKind::Usage | FailureKind::Input => 2,
            FailureKind::Capability => 3,
            FailureKind::Conflict => 4,
            FailureKind::Execution => 1,
        }
    }

    fn json(&self, command: &str) -> Value {
        let mut error = json!({ "code": self.code, "message": self.message });
        if let Some(conflict) = &self.conflict {
            error["conflict"] = conflict.clone();
        }
        json!({
            "schema_version": CLI_SCHEMA_VERSION,
            "product_version": product_version(),
            "command": command,
            "status": if matches!(self.kind, FailureKind::Conflict) { "conflict" } else { "error" },
            "error": error,
        })
    }
}

/// Run a headless command. `args` excludes the `--headless` mode switch.
pub fn run(args: Vec<String>) -> i32 {
    let command = args.first().cloned().unwrap_or_else(|| "headless".into());
    let result = run_command(args);
    match result {
        Ok(value) => {
            if write_json(&value).is_ok() {
                0
            } else {
                1
            }
        }
        Err(failure) => {
            let exit_code = failure.exit_code();
            let value = failure.json(&command);
            if write_json(&value).is_err() {
                return 1;
            }
            exit_code
        }
    }
}

fn run_command(args: Vec<String>) -> Result<Value, CliFailure> {
    let Some(command) = args.first().map(String::as_str) else {
        return Err(CliFailure::usage(usage_text()));
    };
    let command_args = parse_options(&args[1..])?;
    match command {
        "capabilities" => capabilities_command(command_args),
        "inspect" => inspect_command(command_args),
        "transcribe" => transcribe_command(command_args),
        "export" => export_command(command_args),
        "--help" | "-h" | "help" => Ok(json!({
            "schema_version": CLI_SCHEMA_VERSION,
            "product_version": product_version(),
            "command": "help",
            "status": "ok",
            "usage": usage_text(),
        })),
        other => Err(CliFailure::usage(format!(
            "unknown command `{other}`. {}",
            usage_text()
        ))),
    }
}

fn capabilities_command(options: CliOptions) -> Result<Value, CliFailure> {
    options.require_no_operands()?;
    options.require_only(&["json"])?;
    let mut engine = engine_supervisor()?;
    let worker = engine
        .capabilities()
        .map_err(|error| CliFailure::capability("worker_unavailable", error))?;
    let missing_pdf_tools = ["pdfinfo", "pdftotext", "pdftoppm"]
        .into_iter()
        .filter(|name| !executable_on_path(name))
        .collect::<Vec<_>>();
    let transcription_available = worker["ocr"].as_bool().unwrap_or(false);
    let value = json!({
        "schema_version": CLI_SCHEMA_VERSION,
        "product_version": product_version(),
        "command": "capabilities",
        "status": "ok",
        "commands": ["capabilities", "inspect", "transcribe", "export"],
        "input_formats": ["jps", "png", "jpg", "jpeg", "pdf"],
        "transcription_formats": ["png", "jpg", "jpeg", "pdf"],
        "export_formats": ["svg", "pdf", "png", "jpg"],
        "pdf_transcription": {
            "requires": ["pdfinfo", "pdftotext", "pdftoppm"],
            "available": missing_pdf_tools.is_empty() && transcription_available,
            "missing": missing_pdf_tools,
            "ocr_available": transcription_available,
        },
        "transcription_available": transcription_available,
        "png_export_available": worker["png_export"].as_bool().unwrap_or(false),
        "font_policy": worker["font_policy"],
        "font_platform": worker["font_platform"],
        "fonts": worker["fonts"],
        "exit_codes": {
            "0": "success",
            "1": "execution failure",
            "2": "invalid arguments or input",
            "3": "required capability unavailable",
            "4": "input conflicts with an active editing session",
        },
    });
    Ok(value)
}

fn inspect_command(options: CliOptions) -> Result<Value, CliFailure> {
    options.require_only(&["json"])?;
    let input = require_one_operand(&options, "inspect requires one JPS path")?;
    let input = resolve_input_path(input, "jps")?;
    let snapshot = crate::session::read_input_snapshot(&input).map_err(CliFailure::session)?;
    if snapshot.len() > jps_document_io::MAX_JPS_FILE_BYTES {
        return Err(CliFailure::input(
            "input_too_large",
            format!(
                "JPS source exceeds the {}-byte limit",
                jps_document_io::MAX_JPS_FILE_BYTES
            ),
        ));
    }
    let text = String::from_utf8(snapshot)
        .map_err(|_| CliFailure::input("invalid_utf8", "JPS source is not valid UTF-8"))?;
    let mut engine = engine_supervisor()?;
    let score = load_score(&mut engine, &input, &text)?;
    let parse_response = engine
        .parse(render_args(&score))
        .map_err(|error| CliFailure::execution("engine_failed", error))?;
    let parse = response_result(&parse_response, &score.document_id, score.revision, "parse")?;
    let export_response = engine
        .export_svg(render_args(&score))
        .map_err(|error| CliFailure::execution("engine_failed", error))?;
    let export_result = response_result(
        &export_response,
        &score.document_id,
        score.revision,
        "export_svg",
    )?;
    let score_diagnostics = export_result["diagnostics"].clone();
    let (pages, custom_markup_omitted) = crate::commands::exports::export_svg_pages(
        export_response,
        &score.document_id,
        score.revision,
    )
    .map_err(|error| CliFailure::execution("render_failed", error))?;
    let value = json!({
        "schema_version": CLI_SCHEMA_VERSION,
        "product_version": product_version(),
        "command": "inspect",
        "status": "ok",
        "input": path_string(&input)?,
        "document_name": score.name,
        "json_wrapped": score.json_wrapped,
        "encoding_repaired": score.encoding_repaired,
        "source_offset_unit": parse["source_offset_unit"],
        "parse_diagnostics": parse["diagnostics"],
        "score_diagnostics": score_diagnostics,
        "page_count": pages.len(),
        "custom_markup_omitted": custom_markup_omitted,
    });
    Ok(value)
}

fn transcribe_command(options: CliOptions) -> Result<Value, CliFailure> {
    options.require_only(&["out", "issues", "json"])?;
    let input = require_one_operand(&options, "transcribe requires one image or PDF path")?;
    let input = resolve_input_path(input, "image or PDF")?;
    let output = resolve_output_path(options.required_path("out", "--out is required")?)?;
    let issues_path =
        resolve_output_path(options.required_path("issues", "--issues is required")?)?;
    if !has_extension(&output, "jps") {
        return Err(CliFailure::input(
            "invalid_output_path",
            "draft output must use the .jps extension",
        ));
    }
    if !has_extension(&issues_path, "json") {
        return Err(CliFailure::input(
            "invalid_output_path",
            "issues output must use the .json extension",
        ));
    }
    if output == issues_path {
        return Err(CliFailure::input(
            "path_collision",
            "draft and issues output must be different files",
        ));
    }
    reject_existing_outputs(&[output.clone(), issues_path.clone()])?;

    let extension = input
        .extension()
        .and_then(|value| value.to_str())
        .map(str::to_ascii_lowercase)
        .ok_or_else(|| {
            CliFailure::input("unsupported_input", "input has no supported extension")
        })?;
    if !matches!(extension.as_str(), "png" | "jpg" | "jpeg" | "pdf") {
        return Err(CliFailure::input(
            "unsupported_input",
            "transcription supports PNG, JPG, JPEG, and PDF inputs",
        ));
    }
    let source = crate::session::read_input_snapshot(&input).map_err(CliFailure::session)?;
    let input_text = path_string(&input)?;
    let draft_path = path_string(&output)?;
    let issues_path_text = path_string(&issues_path)?;
    let mut engine = engine_supervisor()?;
    let worker = engine
        .capabilities()
        .map_err(|error| CliFailure::capability("worker_unavailable", error))?;
    if !worker["ocr"].as_bool().unwrap_or(false) {
        return Err(CliFailure::capability(
            "transcription_unavailable",
            "this installation does not include the image transcription capability",
        ));
    }
    if extension == "pdf" {
        let missing = ["pdfinfo", "pdftotext", "pdftoppm"]
            .into_iter()
            .filter(|name| !executable_on_path(name))
            .collect::<Vec<_>>();
        if !missing.is_empty() {
            return Err(CliFailure::capability(
                "pdf_tools_missing",
                format!(
                    "PDF transcription requires Poppler tools on PATH: {}",
                    missing.join(", ")
                ),
            ));
        }
    }
    ensure_parent(&output)?;
    ensure_parent(&issues_path)?;
    reject_existing_outputs(&[output.clone(), issues_path.clone()])?;
    let input_directory = tempfile::tempdir()
        .map_err(|error| CliFailure::execution("temporary_file_failed", error.to_string()))?;
    let staged_input = input_directory.path().join(format!("source.{extension}"));
    fs::write(&staged_input, source)
        .map_err(|error| CliFailure::execution("temporary_file_failed", error.to_string()))?;
    let validation_store = input_directory.path().join("validated");
    let worker_input = match extension.as_str() {
        "pdf" => {
            jps_document_io::reference_pdfs::stage_reference_pdfs(
                std::slice::from_ref(&staged_input),
                &validation_store,
            )
            .map_err(|error| CliFailure::input("invalid_pdf", error.to_string()))?
            .into_iter()
            .next()
            .ok_or_else(|| {
                CliFailure::execution("input_stage_failed", "PDF staging returned no input")
            })?
            .path
        }
        _ => {
            jps_document_io::reference_images::stage_reference_images(
                std::slice::from_ref(&staged_input),
                &validation_store,
            )
            .map_err(|error| CliFailure::input("invalid_image", error.to_string()))?
            .into_iter()
            .next()
            .ok_or_else(|| {
                CliFailure::execution("input_stage_failed", "image staging returned no input")
            })?
            .path
        }
    };
    let staged_input_string = path_string(&worker_input)?;
    let document_id = HEADLESS_DOCUMENT_ID.to_owned();
    let revision = 0;
    let response = engine
        .transcribe_with_progress(
            TranscribeArgs {
                document_id: document_id.clone(),
                document_revision: revision,
                path: staged_input_string,
            },
            std::sync::Arc::new(std::sync::atomic::AtomicBool::new(false)),
            |progress| {
                let completed = progress["result"]["completed"].as_u64().unwrap_or(0);
                let total = progress["result"]["total"].as_u64().unwrap_or(0);
                let stage = progress["result"]["stage"].as_str().unwrap_or("working");
                eprintln!("Transcription: {stage} ({completed}/{total})");
            },
        )
        .map_err(|error| CliFailure::execution("transcription_failed", error))?;
    let result = response_result(&response, &document_id, revision, "transcribe")?;
    let draft = result["jps"].as_str().ok_or_else(|| {
        CliFailure::execution(
            "invalid_engine_response",
            "transcription response has no JPS draft",
        )
    })?;
    let issues = result["issues"].as_array().ok_or_else(|| {
        CliFailure::execution(
            "invalid_engine_response",
            "transcription response has invalid issues",
        )
    })?;
    let page_count = result["page_count"].as_u64().ok_or_else(|| {
        CliFailure::execution(
            "invalid_engine_response",
            "transcription response has invalid page count",
        )
    })?;
    let issue_document = json!({
        "schema_version": CLI_SCHEMA_VERSION,
        "status": "review_required",
        "source_offset_unit": "codepoint",
        "page_count": page_count,
        "page_dimensions": result["page_dimensions"],
        "issues": issues,
    });
    let issue_json = serde_json::to_vec_pretty(&issue_document)
        .map_err(|error| CliFailure::execution("json_encode_failed", error.to_string()))?;
    publish_new_files(vec![
        (output.clone(), draft.as_bytes().to_vec()),
        (issues_path.clone(), issue_json),
    ])?;
    let value = json!({
        "schema_version": CLI_SCHEMA_VERSION,
        "product_version": product_version(),
        "command": "transcribe",
        "status": "ok",
        "input": input_text,
        "draft_path": draft_path,
        "issues_path": issues_path_text,
        "page_count": page_count,
        "issue_count": issues.len(),
        "issues": issues,
        "source_offset_unit": "codepoint",
    });
    Ok(value)
}

fn export_command(options: CliOptions) -> Result<Value, CliFailure> {
    options.require_only(&["format", "out", "out-dir", "dpi", "json"])?;
    let input = require_one_operand(&options, "export requires one JPS path")?;
    let input = resolve_input_path(input, "jps")?;
    let format_name = options.required_value("format", "--format is required")?;
    let format = match format_name.as_str() {
        "svg" => ExportFormat::Svg,
        "pdf" => ExportFormat::Pdf,
        "png" => ExportFormat::Png,
        "jpg" => ExportFormat::Jpg,
        _ => {
            return Err(CliFailure::usage(
                "--format must be one of svg, pdf, png, or jpg",
            ));
        }
    };
    let dpi = match options.value("dpi") {
        None if matches!(format, ExportFormat::Png | ExportFormat::Jpg) => 96,
        None => 96,
        Some(value) if matches!(format, ExportFormat::Png | ExportFormat::Jpg) => value
            .parse::<u16>()
            .ok()
            .filter(|dpi| matches!(dpi, 96 | 300))
            .ok_or_else(|| CliFailure::usage("--dpi must be 96 or 300"))?,
        Some(_) => {
            return Err(CliFailure::usage(
                "--dpi is only valid for PNG and JPG export",
            ))
        }
    };
    let output_option = options.value("out");
    let output_dir_option = options.value("out-dir");
    if output_option.is_some() == output_dir_option.is_some() {
        return Err(CliFailure::usage(
            "provide exactly one of --out or --out-dir",
        ));
    }
    if format == ExportFormat::Pdf && output_option.is_none() {
        return Err(CliFailure::usage("PDF export requires --out"));
    }
    let output_base = if let Some(path) = output_option {
        resolve_output_path(PathBuf::from(path.as_str()))?
    } else {
        let directory = resolve_output_directory(output_dir_option.expect("checked above"))?;
        let stem = input
            .file_stem()
            .and_then(|value| value.to_str())
            .filter(|value| !value.is_empty())
            .ok_or_else(|| CliFailure::input("invalid_input_path", "input filename is invalid"))?;
        directory.join(format!("{stem}.{}", format_extension(format)))
    };
    if output_base
        .extension()
        .and_then(|value| value.to_str())
        .is_none_or(|extension| !extension.eq_ignore_ascii_case(format_extension(format)))
    {
        return Err(CliFailure::input(
            "invalid_output_path",
            format!(
                "export output must use the .{} extension",
                format_extension(format)
            ),
        ));
    }
    if format == ExportFormat::Svg && options.value("dpi").is_some() {
        return Err(CliFailure::usage(
            "--dpi is only valid for PNG and JPG export",
        ));
    }
    let source = crate::session::read_input_snapshot(&input).map_err(CliFailure::session)?;
    if source.len() > jps_document_io::MAX_JPS_FILE_BYTES {
        return Err(CliFailure::input(
            "input_too_large",
            format!(
                "JPS source exceeds the {}-byte limit",
                jps_document_io::MAX_JPS_FILE_BYTES
            ),
        ));
    }
    let text = String::from_utf8(source)
        .map_err(|_| CliFailure::input("invalid_utf8", "JPS source is not valid UTF-8"))?;
    let mut engine = engine_supervisor()?;
    let score = load_score(&mut engine, &input, &text)?;
    let response = engine
        .export_svg(render_args(&score))
        .map_err(|error| CliFailure::execution("engine_failed", error))?;
    let diagnostics = response["result"]["diagnostics"].clone();
    let input_text = path_string(&input)?;
    let _output_base_text = path_string(&output_base)?;
    let (svg_pages, custom_markup_omitted) =
        crate::commands::exports::export_svg_pages(response, &score.document_id, score.revision)
            .map_err(|error| CliFailure::execution("render_failed", error))?;
    ensure_parent(&output_base)?;
    let output_base = resolve_output_path(output_base)?;
    let output_count = if format == ExportFormat::Pdf {
        1
    } else {
        svg_pages.len()
    };
    let existing =
        jps_document_io::file_exports::existing_export_targets(&output_base, format, output_count)
            .map_err(|error| CliFailure::input("output_path_invalid", error.to_string()))?;
    if !existing.is_empty() {
        return Err(CliFailure::input(
            "output_exists",
            "one or more export output files already exist; choose another output path",
        ));
    }
    let outputs = match format {
        ExportFormat::Svg => publish_svg_pages(&output_base, &svg_pages, &[]),
        ExportFormat::Pdf => {
            let pdf = export_pdf(&svg_pages)
                .map_err(|error| CliFailure::execution("export_failed", error.to_string()))?;
            let pages: [&[u8]; 1] = [&pdf];
            publish_export_pages(&output_base, format, &pages, &[])
        }
        ExportFormat::Jpg => {
            let pages = export_jpg_pages(&svg_pages, dpi)
                .map_err(|error| CliFailure::execution("export_failed", error.to_string()))?;
            let references = pages.iter().map(Vec::as_slice).collect::<Vec<_>>();
            publish_export_pages(&output_base, format, &references, &[])
        }
        ExportFormat::Png => {
            let pages = export_png_pages(&svg_pages, dpi)
                .map_err(|error| CliFailure::execution("export_failed", error.to_string()))?;
            let references = pages.iter().map(Vec::as_slice).collect::<Vec<_>>();
            publish_export_pages(&output_base, format, &references, &[])
        }
    }
    .map_err(|error| CliFailure::execution("export_failed", error.to_string()))?;
    let output_paths = outputs
        .iter()
        .map(|path| path_string(path))
        .collect::<Result<Vec<_>, _>>()?;
    let value = json!({
        "schema_version": CLI_SCHEMA_VERSION,
        "product_version": product_version(),
        "command": "export",
        "status": "ok",
        "input": input_text,
        "format": format_name,
        "dpi": if matches!(format, ExportFormat::Png | ExportFormat::Jpg) { Some(dpi) } else { None },
        "page_count": svg_pages.len(),
        "outputs": output_paths,
        "score_diagnostics": diagnostics,
        "custom_markup_omitted": custom_markup_omitted,
    });
    Ok(value)
}

struct LoadedScore {
    document_id: String,
    revision: u64,
    name: String,
    code: String,
    custom_code: String,
    page_config: Value,
    json_wrapped: bool,
    encoding_repaired: bool,
}

fn load_score(
    engine: &mut EngineSupervisor,
    input: &Path,
    text: &str,
) -> Result<LoadedScore, CliFailure> {
    let name = input
        .file_name()
        .and_then(|value| value.to_str())
        .ok_or_else(|| CliFailure::input("invalid_input_path", "JPS filename is not valid UTF-8"))?
        .to_owned();
    let document_id = HEADLESS_DOCUMENT_ID.to_owned();
    let revision = 0;
    let response = engine
        .load_document(LoadDocumentArgs {
            document_id: document_id.clone(),
            document_revision: revision,
            name: name.clone(),
            text: text.to_owned(),
        })
        .map_err(|error| CliFailure::execution("engine_failed", error))?;
    let result = response_result(&response, &document_id, revision, "load_document")
        .map_err(|failure| CliFailure::input("invalid_jps", failure.message))?;
    let document = result.get("document").ok_or_else(|| {
        CliFailure::execution(
            "invalid_engine_response",
            "document loader returned no document",
        )
    })?;
    let code = document["code"].as_str().ok_or_else(|| {
        CliFailure::execution(
            "invalid_engine_response",
            "document loader returned invalid code",
        )
    })?;
    let custom_code = document["custom_code"].as_str().ok_or_else(|| {
        CliFailure::execution(
            "invalid_engine_response",
            "document loader returned invalid custom code",
        )
    })?;
    let mut page_config = document["page_config"].clone();
    if !page_config.is_object() {
        return Err(CliFailure::execution(
            "invalid_engine_response",
            "document loader returned invalid page settings",
        ));
    }
    if let Some(settings) = page_config.as_object_mut() {
        // The GUI's createDocument adapter removes this retired compatibility field.
        settings.remove("_font_sources");
    }
    Ok(LoadedScore {
        document_id,
        revision,
        name,
        code: code.to_owned(),
        custom_code: custom_code.to_owned(),
        page_config,
        json_wrapped: document["json_wrapped"].as_bool().unwrap_or(false),
        encoding_repaired: document["encoding_repaired"].as_bool().unwrap_or(false),
    })
}

fn render_args(score: &LoadedScore) -> RenderArgs {
    RenderArgs {
        document_id: score.document_id.clone(),
        document_revision: score.revision,
        name: score.name.clone(),
        code: score.code.clone(),
        custom_code: score.custom_code.clone(),
        page_config: score.page_config.clone(),
    }
}

fn response_result<'a>(
    response: &'a Value,
    document_id: &str,
    revision: u64,
    operation: &str,
) -> Result<&'a Value, CliFailure> {
    if response["document_id"].as_str() != Some(document_id)
        || response["document_revision"].as_u64() != Some(revision)
    {
        return Err(CliFailure::execution(
            "engine_identity_mismatch",
            format!("{operation} response identity mismatch"),
        ));
    }
    if response["status"] != "ok" {
        let code = response["error"]["code"]
            .as_str()
            .unwrap_or("engine_operation_failed")
            .to_owned();
        let message = response["error"]["message"]
            .as_str()
            .unwrap_or("Python engine operation failed")
            .to_owned();
        return Err(CliFailure::execution(code, message));
    }
    response.get("result").ok_or_else(|| {
        CliFailure::execution(
            "invalid_engine_response",
            format!("{operation} response has no result"),
        )
    })
}

fn product_version() -> &'static str {
    include_str!("../../../../VERSION").trim()
}

fn usage_text() -> &'static str {
    "Usage: octopus --headless capabilities --json | inspect <score.jps> --json | transcribe <input.png|jpg|jpeg|pdf> --out <draft.jps> --issues <issues.json> --json | export <score.jps> --format svg|pdf|png|jpg --out <target.ext> [--dpi 96|300] --json | export <score.jps> --format svg|png|jpg --out-dir <directory> [--dpi 96|300] --json"
}

fn write_json(value: &Value) -> io::Result<()> {
    let stdout = io::stdout();
    let mut output = stdout.lock();
    serde_json::to_writer(&mut output, value)?;
    output.write_all(b"\n")?;
    output.flush()
}

#[cfg(test)]
mod tests {
    use super::{CliFailure, CLI_SCHEMA_VERSION};
    use crate::session::{SessionConflict, SessionError, SessionOwner};
    use serde_json::json;

    #[test]
    fn conflict_is_structured_and_uses_the_documented_exit_code() {
        let failure = CliFailure::session(SessionError::Conflict(SessionConflict {
            path: "C:/scores/简谱.jps".into(),
            sessions: vec![SessionOwner {
                window_label: "main".into(),
                document_name: "简谱.jps".into(),
                dirty: true,
                conflict_latched: true,
                process_id: 42,
            }],
        }));

        let output = failure.json("inspect");
        assert_eq!(failure.exit_code(), 4);
        assert_eq!(output["schema_version"], CLI_SCHEMA_VERSION);
        assert_eq!(output["status"], "conflict");
        assert_eq!(output["error"]["code"], "active_session_conflict");
        assert_eq!(
            output["error"]["conflict"],
            json!({
                "path": "C:/scores/简谱.jps",
                "sessions": [{
                    "windowLabel": "main",
                    "documentName": "简谱.jps",
                    "dirty": true,
                    "conflictLatched": true,
                    "processId": 42
                }]
            })
        );
    }
}
