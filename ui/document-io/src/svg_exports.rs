use std::path::{Path, PathBuf};

use crate::file_exports::{publish_export_pages, ExportFormat};
use crate::DocumentIoError;

pub fn publish_svg_pages(
    selected_path: &Path,
    pages: &[String],
    replace_existing: bool,
) -> Result<Vec<PathBuf>, DocumentIoError> {
    let pages = pages.iter().map(String::as_bytes).collect::<Vec<_>>();
    publish_export_pages(selected_path, ExportFormat::Svg, &pages, replace_existing)
}
