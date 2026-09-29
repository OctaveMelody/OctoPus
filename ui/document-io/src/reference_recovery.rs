use std::collections::{HashMap, HashSet};

use serde_json::Value;

use crate::reference_images::{
    MAX_REFERENCE_IMAGE_BYTES, MAX_REFERENCE_IMAGE_FILES, MAX_REFERENCE_SET_BYTES,
};
use crate::reference_pdfs::MAX_REFERENCE_PDF_BYTES;

pub fn validate_recovery_references(snapshot: Option<&str>) -> Result<(), String> {
    let Some(snapshot) = snapshot else {
        return Ok(());
    };
    let value: Value = serde_json::from_str(snapshot)
        .map_err(|error| format!("recovery snapshot is invalid JSON: {error}"))?;
    let version = value.get("version").and_then(Value::as_u64);
    if version != Some(3) && version != Some(4) {
        return Ok(());
    }
    let references = value
        .get("references")
        .ok_or_else(|| "recovery reference list is invalid".to_owned())?;
    let pages = references
        .get("images")
        .and_then(Value::as_array)
        .ok_or_else(|| "recovery reference image list is invalid".to_owned())?;
    if version == Some(3) {
        if pages.len() > MAX_REFERENCE_IMAGE_FILES {
            return Err("recovery reference image count exceeds the limit".into());
        }
        if pages
            .iter()
            .any(|page| page.get("id").and_then(Value::as_str).is_none())
        {
            return Err("recovery reference image ID is invalid".into());
        }
        return Ok(());
    }

    validate_v4_references(references, pages)
}

fn validate_v4_references(references: &Value, pages: &[Value]) -> Result<(), String> {
    let pdfs = references
        .get("pdfs")
        .and_then(Value::as_array)
        .ok_or_else(|| "recovery reference PDF list is invalid".to_owned())?;
    if pages.len() > MAX_REFERENCE_IMAGE_FILES || pdfs.len() > MAX_REFERENCE_IMAGE_FILES {
        return Err("recovery reference page or PDF count exceeds the limit".into());
    }

    let mut pdf_metadata = HashMap::new();
    let mut total_bytes = 0_u64;
    for pdf in pdfs {
        let id = pdf
            .get("id")
            .and_then(Value::as_str)
            .filter(|id| is_pdf_asset_id(id))
            .ok_or_else(|| "recovery reference PDF ID is invalid".to_owned())?;
        if pdf.get("path").is_some() || !valid_reference_name(pdf.get("name")) {
            return Err("recovery reference PDF metadata is invalid".into());
        }
        pdf.get("sha256")
            .and_then(Value::as_str)
            .filter(|hash| {
                hash.len() == 64
                    && hash
                        .bytes()
                        .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
            })
            .ok_or_else(|| "recovery reference PDF hash is invalid".to_owned())?;
        let byte_length = pdf
            .get("byteLength")
            .and_then(Value::as_u64)
            .filter(|size| (1..=MAX_REFERENCE_PDF_BYTES as u64).contains(size))
            .ok_or_else(|| "recovery reference PDF size is invalid".to_owned())?;
        let page_count = pdf
            .get("pageCount")
            .and_then(Value::as_u64)
            .filter(|count| (1..=MAX_REFERENCE_IMAGE_FILES as u64).contains(count))
            .ok_or_else(|| "recovery reference PDF page count is invalid".to_owned())?;
        if pdf_metadata.insert(id.to_owned(), page_count).is_some() {
            return Err("recovery reference PDF IDs must be unique".into());
        }
        total_bytes = total_bytes
            .checked_add(byte_length)
            .filter(|size| *size <= MAX_REFERENCE_SET_BYTES)
            .ok_or_else(|| "recovery reference set exceeds the byte limit".to_owned())?;
    }

    let mut page_ids = HashSet::new();
    let mut referenced_pdfs = HashSet::new();
    let mut asset_ids = HashSet::new();
    for page in pages {
        let id = page
            .get("id")
            .and_then(Value::as_str)
            .ok_or_else(|| "recovery reference page ID is invalid".to_owned())?;
        if !page_ids.insert(id) {
            return Err("recovery reference page IDs must be unique".into());
        }
        if page.get("path").is_some() {
            return Err("recovery reference page contains a local path".into());
        }
        let kind = page.get("kind").and_then(Value::as_str);
        if page.get("kind").is_some() && !matches!(kind, Some("image" | "pdf-page")) {
            return Err("recovery reference page kind is unsupported".into());
        }
        if kind == Some("pdf-page") {
            let pdf_id = page
                .get("pdfId")
                .and_then(Value::as_str)
                .filter(|pdf_id| pdf_metadata.contains_key(*pdf_id))
                .ok_or_else(|| "recovery reference PDF page source is missing".to_owned())?;
            let page_number = page
                .get("pageNumber")
                .and_then(Value::as_u64)
                .filter(|number| *number <= pdf_metadata[pdf_id])
                .filter(|number| *number > 0)
                .ok_or_else(|| "recovery reference PDF page number is invalid".to_owned())?;
            let expected_id = format!("pdfpage-{}-{page_number}", &pdf_id[4..pdf_id.len() - 4]);
            if id != expected_id
                || !valid_reference_name(page.get("name"))
                || !matches!(
                    page.get("pageRotation").and_then(Value::as_u64),
                    Some(0 | 90 | 180 | 270)
                )
                || page.get("renderScale").and_then(Value::as_f64) != Some(1.0)
                || page.get("orientation").and_then(Value::as_u64) != Some(1)
                || !valid_reference_numbers(page.get("pageBox"), 4, 1_000_000.0)
                || !valid_reference_numbers(page.get("transform"), 6, 1_000_000.0)
            {
                return Err("recovery reference PDF page metadata is invalid".into());
            }
            let width = page
                .get("width")
                .and_then(Value::as_u64)
                .unwrap_or_default();
            let height = page
                .get("height")
                .and_then(Value::as_u64)
                .unwrap_or_default();
            if width == 0
                || height == 0
                || width > 50_000
                || height > 50_000
                || width.saturating_mul(height) > 40_000_000
            {
                return Err("recovery reference PDF page dimensions are invalid".into());
            }
            referenced_pdfs.insert(pdf_id.to_owned());
            asset_ids.insert(pdf_id.to_owned());
        } else {
            let mime = page.get("mimeType").and_then(Value::as_str);
            if !is_image_asset_id(id)
                || !valid_reference_name(page.get("name"))
                || !matches!(mime, Some("image/png" | "image/jpeg"))
                || (id.ends_with(".png") && mime != Some("image/png"))
                || (id.ends_with(".jpg") && mime != Some("image/jpeg"))
            {
                return Err("recovery reference image metadata is invalid".into());
            }
            let byte_length = page
                .get("byteLength")
                .and_then(Value::as_u64)
                .filter(|size| (1..=MAX_REFERENCE_IMAGE_BYTES as u64).contains(size))
                .ok_or_else(|| "recovery reference image size is invalid".to_owned())?;
            let width = page
                .get("width")
                .and_then(Value::as_u64)
                .unwrap_or_default();
            let height = page
                .get("height")
                .and_then(Value::as_u64)
                .unwrap_or_default();
            let orientation = page
                .get("orientation")
                .and_then(Value::as_u64)
                .unwrap_or_default();
            if width == 0
                || height == 0
                || width.saturating_mul(height) > 40_000_000
                || !(1..=8).contains(&orientation)
            {
                return Err("recovery reference image dimensions are invalid".into());
            }
            total_bytes = total_bytes
                .checked_add(byte_length)
                .filter(|size| *size <= MAX_REFERENCE_SET_BYTES)
                .ok_or_else(|| "recovery reference set exceeds the byte limit".to_owned())?;
            asset_ids.insert(id.to_owned());
        }
    }
    if referenced_pdfs.len() != pdf_metadata.len() {
        return Err("recovery reference PDF has no selected pages".into());
    }
    if asset_ids.len() > MAX_REFERENCE_IMAGE_FILES {
        return Err("recovery reference asset count exceeds the limit".into());
    }
    Ok(())
}

fn is_pdf_asset_id(id: &str) -> bool {
    id.strip_prefix("pdf-")
        .and_then(|stem| stem.strip_suffix(".pdf"))
        .is_some_and(|token| {
            !token.is_empty() && token.bytes().all(|byte| byte.is_ascii_alphanumeric())
        })
}

fn is_image_asset_id(id: &str) -> bool {
    let Some(stem) = id.strip_prefix("img-") else {
        return false;
    };
    let Some((token, extension)) = stem.rsplit_once('.') else {
        return false;
    };
    !token.is_empty()
        && token.bytes().all(|byte| byte.is_ascii_alphanumeric())
        && matches!(extension, "png" | "jpg")
}

fn valid_reference_name(value: Option<&Value>) -> bool {
    value.and_then(Value::as_str).is_some_and(|name| {
        !name.trim().is_empty()
            && name.len() <= 255
            && !name
                .chars()
                .any(|character| matches!(character, '/' | '\\' | '\0'))
    })
}

fn valid_reference_numbers(value: Option<&Value>, length: usize, maximum: f64) -> bool {
    value.and_then(Value::as_array).is_some_and(|numbers| {
        numbers.len() == length
            && numbers.iter().all(|number| {
                number
                    .as_f64()
                    .is_some_and(|number| number.is_finite() && number.abs() <= maximum)
            })
    })
}

#[cfg(test)]
mod tests {
    use serde_json::{json, Value};

    use super::validate_recovery_references;

    fn pdf_page(pdf_id: &str, page_number: u64) -> Value {
        json!({
            "id": format!("pdfpage-{}-{page_number}", &pdf_id[4..pdf_id.len() - 4]),
            "kind": "pdf-page",
            "name": "scan.pdf",
            "pdfId": pdf_id,
            "pageNumber": page_number,
            "pageBox": [0, 0, 595, 842],
            "pageRotation": 0,
            "renderScale": 1,
            "transform": [1, 0, 0, -1, 0, 842],
            "width": 595,
            "height": 842,
            "orientation": 1
        })
    }

    fn image_page() -> Value {
        json!({
            "id": "img-Ab12.png",
            "kind": "image",
            "name": "scan.png",
            "mimeType": "image/png",
            "byteLength": 128,
            "width": 320,
            "height": 240,
            "orientation": 1
        })
    }

    fn pdf_manifest(id: &str) -> Value {
        json!({
            "id": id,
            "name": "scan.pdf",
            "byteLength": 512,
            "sha256": "a".repeat(64),
            "pageCount": 2
        })
    }

    fn v4_snapshot(pages: Vec<Value>, pdfs: Vec<Value>) -> String {
        json!({
            "version": 4,
            "references": { "images": pages, "pdfs": pdfs }
        })
        .to_string()
    }

    #[test]
    fn accepts_legacy_v3_and_mixed_v4_managed_references() {
        let v3 = json!({
            "version": 3,
            "references": { "images": [{ "id": "img-Ab12.png" }] }
        })
        .to_string();
        assert!(validate_recovery_references(Some(&v3)).is_ok());

        let pdf_id = "pdf-Cd34.pdf";
        let v4 = v4_snapshot(
            vec![image_page(), pdf_page(pdf_id, 1)],
            vec![pdf_manifest(pdf_id)],
        );
        assert!(validate_recovery_references(Some(&v4)).is_ok());
    }

    #[test]
    fn rejects_invalid_pdf_identity_geometry_and_persisted_paths() {
        let pdf_id = "pdf-Cd34.pdf";
        let mut bad_hash = pdf_manifest(pdf_id);
        bad_hash["sha256"] = json!("invalid");
        assert!(validate_recovery_references(Some(&v4_snapshot(
            vec![pdf_page(pdf_id, 1)],
            vec![bad_hash],
        )))
        .is_err());

        let mut bad_geometry = pdf_page(pdf_id, 1);
        bad_geometry["width"] = json!(9000);
        bad_geometry["height"] = json!(9000);
        assert!(validate_recovery_references(Some(&v4_snapshot(
            vec![bad_geometry],
            vec![pdf_manifest(pdf_id)],
        )))
        .is_err());

        let mut path = pdf_manifest(pdf_id);
        path["path"] = json!("/tmp/score.pdf");
        assert!(validate_recovery_references(Some(&v4_snapshot(
            vec![pdf_page(pdf_id, 1)],
            vec![path],
        )))
        .is_err());
    }

    #[test]
    fn rejects_unreferenced_sources_and_out_of_range_pages() {
        let pdf_id = "pdf-Cd34.pdf";
        assert!(validate_recovery_references(Some(&v4_snapshot(
            vec![pdf_page(pdf_id, 3)],
            vec![pdf_manifest(pdf_id)],
        )))
        .is_err());
        assert!(validate_recovery_references(Some(&v4_snapshot(
            vec![image_page()],
            vec![pdf_manifest(pdf_id)],
        )))
        .is_err());
    }

    #[test]
    fn enforces_the_aggregate_reference_byte_limit() {
        let mut pages = Vec::new();
        let mut pdfs = Vec::new();
        for index in 0..6 {
            let id = format!("pdf-Ab{index}2.pdf");
            pages.push(pdf_page(&id, 1));
            let mut manifest = pdf_manifest(&id);
            manifest["byteLength"] = json!(100 * 1024 * 1024);
            pdfs.push(manifest);
        }
        assert!(validate_recovery_references(Some(&v4_snapshot(pages, pdfs))).is_err());
    }
}
