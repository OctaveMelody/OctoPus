use std::fs::File;
use std::io::{Read, Write};
use std::path::{Path, PathBuf};

use sha2::{Digest, Sha256};
use tempfile::Builder;

use crate::reference_images::{
    ensure_store, is_managed_asset_id, managed_store_size, remove_reference_images,
    ReferenceImageError, MAX_REFERENCE_CACHE_BYTES, MAX_REFERENCE_IMAGE_FILES,
    MAX_REFERENCE_SET_BYTES,
};

pub const MAX_REFERENCE_PDF_BYTES: usize = 100 * 1024 * 1024;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct StagedReferencePdf {
    pub id: String,
    pub path: PathBuf,
    pub name: String,
    pub byte_length: usize,
    pub sha256: String,
}

pub fn stage_reference_pdfs(
    paths: &[PathBuf],
    store: &Path,
) -> Result<Vec<StagedReferencePdf>, ReferenceImageError> {
    if paths.is_empty() {
        return Err(ReferenceImageError::EmptyBatch);
    }
    if paths.len() > MAX_REFERENCE_IMAGE_FILES {
        return Err(ReferenceImageError::TooManyImages);
    }
    ensure_store(store)?;
    let (existing_bytes, existing_count) = managed_store_size(store)?;
    if existing_count.saturating_add(paths.len()) > MAX_REFERENCE_IMAGE_FILES * 2 {
        return Err(ReferenceImageError::TooManyImages);
    }

    let mut staged = Vec::with_capacity(paths.len());
    let mut total_bytes = existing_bytes;
    let mut batch_bytes = 0_u64;
    for path in paths {
        match stage_one(path, store, &mut total_bytes, &mut batch_bytes) {
            Ok(pdf) => staged.push(pdf),
            Err(error) => {
                let ids = staged
                    .iter()
                    .map(|pdf: &StagedReferencePdf| pdf.id.clone())
                    .collect::<Vec<_>>();
                let _ = remove_reference_images(store, &ids);
                return Err(error);
            }
        }
    }
    Ok(staged)
}

fn stage_one(
    source: &Path,
    store: &Path,
    total_bytes: &mut u64,
    batch_bytes: &mut u64,
) -> Result<StagedReferencePdf, ReferenceImageError> {
    let extension = source
        .extension()
        .and_then(|value| value.to_str())
        .unwrap_or_default();
    if !extension.eq_ignore_ascii_case("pdf") {
        return Err(ReferenceImageError::UnsupportedPdfExtension);
    }
    let file = File::open(source)?;
    if !file.metadata()?.is_file() {
        return Err(ReferenceImageError::InvalidTarget);
    }
    let mut bytes = Vec::new();
    Read::take(file, MAX_REFERENCE_PDF_BYTES as u64 + 1).read_to_end(&mut bytes)?;
    if bytes.len() > MAX_REFERENCE_PDF_BYTES {
        return Err(ReferenceImageError::PdfTooLarge);
    }
    let header = &bytes[..bytes.len().min(1024)];
    if !header.windows(5).any(|window| window == b"%PDF-") {
        return Err(ReferenceImageError::InvalidPdf);
    }
    *batch_bytes = batch_bytes
        .checked_add(bytes.len() as u64)
        .filter(|size| *size <= MAX_REFERENCE_SET_BYTES)
        .ok_or(ReferenceImageError::PdfSetTooLarge)?;
    *total_bytes = total_bytes
        .checked_add(bytes.len() as u64)
        .filter(|size| *size <= MAX_REFERENCE_CACHE_BYTES)
        .ok_or(ReferenceImageError::CacheTooLarge)?;

    let name = source
        .file_name()
        .and_then(|value| value.to_str())
        .ok_or(ReferenceImageError::InvalidTarget)?
        .to_owned();
    let hash = Sha256::digest(&bytes);
    let sha256 = hash.iter().map(|byte| format!("{byte:02x}")).collect();
    let mut temporary = Builder::new()
        .prefix("pdf-")
        .suffix(".pdf")
        .tempfile_in(store)?;
    temporary.write_all(&bytes)?;
    temporary.as_file().sync_all()?;
    let (_, path) = temporary
        .keep()
        .map_err(|error| ReferenceImageError::Io(error.error))?;
    let id = path
        .file_name()
        .and_then(|value| value.to_str())
        .filter(|name| is_managed_asset_id(name))
        .ok_or(ReferenceImageError::InvalidAssetId)?
        .to_owned();
    Ok(StagedReferencePdf {
        id,
        path,
        name,
        byte_length: bytes.len(),
        sha256,
    })
}

#[cfg(test)]
mod tests {
    use std::fs;

    use tempfile::tempdir;

    use super::{stage_reference_pdfs, MAX_REFERENCE_PDF_BYTES};
    use crate::reference_images::{
        prune_reference_images, resolve_reference_image_paths, ReferenceImageError,
    };

    #[test]
    fn validates_and_stages_immutable_pdf_copy_with_hash() {
        let root = tempdir().expect("temp directory");
        let input = root.path().join("score.PDF");
        let store = root.path().join("cache");
        let bytes = b"%PDF-1.7\nnot parsed here";
        fs::write(&input, bytes).expect("write source");

        let staged = stage_reference_pdfs(std::slice::from_ref(&input), &store)
            .expect("stage PDF")
            .remove(0);
        assert_eq!(staged.name, "score.PDF");
        assert_eq!(staged.byte_length, bytes.len());
        assert_eq!(fs::read(&staged.path).expect("read managed copy"), bytes);
        assert_eq!(
            staged.sha256,
            "3dd9cad7e5b0aa8efec9ace3bee50fc9c3cd1fe884dae94bdc8e7ad1193f3135"
        );
        assert_eq!(
            resolve_reference_image_paths(&store, std::slice::from_ref(&staged.id))
                .expect("resolve managed PDF")
                .len(),
            1
        );
        prune_reference_images(&store, std::slice::from_ref(&staged.id))
            .expect("retain referenced PDF");
        assert!(staged.path.exists());
        fs::write(&input, b"changed source").expect("mutate original");
        assert_eq!(
            fs::read(&staged.path).expect("managed copy is immutable"),
            bytes
        );
        prune_reference_images(&store, &[]).expect("prune managed asset");
        assert!(!staged.path.exists());
    }

    #[test]
    fn rejects_bad_signature_extension_and_oversized_pdf_without_cache_changes() {
        let root = tempdir().expect("temp directory");
        let store = root.path().join("cache");
        let wrong_extension = root.path().join("score.txt");
        fs::write(&wrong_extension, b"%PDF-1.7").expect("write input");
        assert!(matches!(
            stage_reference_pdfs(std::slice::from_ref(&wrong_extension), &store),
            Err(ReferenceImageError::UnsupportedPdfExtension)
        ));
        let invalid = root.path().join("invalid.pdf");
        fs::write(&invalid, b"not pdf").expect("write input");
        assert!(matches!(
            stage_reference_pdfs(std::slice::from_ref(&invalid), &store),
            Err(ReferenceImageError::InvalidPdf)
        ));
        let oversized = root.path().join("oversized.pdf");
        let file = fs::File::create(&oversized).expect("create input");
        file.set_len(MAX_REFERENCE_PDF_BYTES as u64 + 1)
            .expect("set size");
        assert!(matches!(
            stage_reference_pdfs(std::slice::from_ref(&oversized), &store),
            Err(ReferenceImageError::PdfTooLarge)
        ));
        assert_eq!(fs::read_dir(&store).expect("cache").count(), 0);
    }
}
