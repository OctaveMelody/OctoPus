//! Newline-delimited worker framing and response-envelope validation.

use serde_json::Value;
use std::io::{self, BufRead, Write};

pub(super) const PROTOCOL_VERSION: &str = "1.7.0";
pub(super) const MAX_REQUEST_BYTES: usize = 10 * 1024 * 1024;
pub(super) const MAX_RESPONSE_BYTES: usize = 64 * 1024 * 1024;

pub(super) fn write_frame(writer: &mut impl Write, request: &Value) -> Result<(), String> {
    let bytes = serde_json::to_vec(request).map_err(io_message)?;
    if bytes.len() + 1 > MAX_REQUEST_BYTES {
        return Err("handshake exceeds the protocol byte limit".into());
    }
    write_request(writer, &bytes)
}

/// Write an already bounded encoded request, adding its newline and flushing.
pub(super) fn write_request(writer: &mut impl Write, bytes: &[u8]) -> Result<(), String> {
    writer.write_all(bytes).map_err(io_message)?;
    writer.write_all(b"\n").map_err(io_message)?;
    writer.flush().map_err(io_message)
}

pub(super) fn read_response(reader: &mut impl BufRead) -> Result<Value, String> {
    let line = read_bounded_line(reader, MAX_RESPONSE_BYTES).map_err(io_message)?;
    if line.is_empty() {
        return Err("Python engine closed its output".into());
    }
    serde_json::from_slice(&line).map_err(|error| format!("invalid engine JSON response: {error}"))
}

pub(super) fn read_bounded_line(reader: &mut impl BufRead, limit: usize) -> io::Result<Vec<u8>> {
    let mut line = Vec::new();
    loop {
        let available = reader.fill_buf()?;
        if available.is_empty() {
            return Ok(line);
        }
        let length = available
            .iter()
            .position(|byte| *byte == b'\n')
            .map_or(available.len(), |index| index + 1);
        if line.len() + length > limit {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "Python response exceeds the protocol byte limit",
            ));
        }
        let complete = available.get(length - 1) == Some(&b'\n');
        line.extend_from_slice(&available[..length]);
        reader.consume(length);
        if complete {
            return Ok(line);
        }
    }
}

pub(super) fn validate_response(
    response: &Value,
    request_id: &str,
    document_id: &str,
    revision: u64,
    expected_generation: Option<&str>,
    handshake: bool,
) -> Result<String, String> {
    let generation = response["engine_generation"]
        .as_str()
        .filter(|value| !value.is_empty() && value.len() <= 128)
        .ok_or("engine response has invalid generation")?;
    if response["protocol_version"] != PROTOCOL_VERSION
        || response["request_id"] != request_id
        || response["document_id"] != document_id
        || response["document_revision"].as_u64() != Some(revision)
        || !matches!(response["status"].as_str(), Some("ok" | "error"))
        || expected_generation.is_some_and(|expected| expected != generation)
    {
        return Err("engine response protocol, identity, status, or generation mismatch".into());
    }
    if response["status"] == "ok" {
        let result = response
            .get("result")
            .ok_or("successful response has no result")?;
        if handshake
            && (!result["operations"].as_array().is_some_and(|operations| {
                [
                    "handshake",
                    "load_document",
                    "render",
                    "parse",
                    "export_svg",
                    "render_page",
                    "serialize_document",
                    "transcribe",
                ]
                .iter()
                .all(|expected| operations.iter().any(|operation| operation == expected))
            }) || !result["custom_svg_display"].is_boolean()
                || !result["ocr"].is_boolean()
                || !result["png_export"].is_boolean())
        {
            return Err("engine handshake has invalid operations or capabilities".into());
        }
    } else if !response.get("error").is_some_and(Value::is_object) {
        return Err("failed response has no structured error".into());
    }
    if handshake && response["status"] == "error" {
        return Err(format!("engine handshake failed: {}", response["error"]));
    }
    Ok(generation.to_owned())
}

fn io_message(error: impl std::fmt::Display) -> String {
    error.to_string()
}
