use std::path::{Path, PathBuf};

use crate::reference_images::{
    remove_reference_images, stage_reference_images, ReferenceImageError, StagedReferenceImage,
    MAX_REFERENCE_IMAGE_FILES, MAX_REFERENCE_SET_BYTES,
};
use crate::reference_pdfs::{stage_reference_pdfs, StagedReferencePdf};

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct StagedReferenceAssets {
    pub images: Vec<StagedReferenceImage>,
    pub pdfs: Vec<StagedReferencePdf>,
    pub order: Vec<String>,
}

#[derive(Clone, Copy)]
enum AssetKind {
    Image,
    Pdf,
}

pub fn stage_reference_assets(
    paths: &[PathBuf],
    store: &Path,
) -> Result<StagedReferenceAssets, ReferenceImageError> {
    if paths.is_empty() {
        return Err(ReferenceImageError::EmptyBatch);
    }
    if paths.len() > MAX_REFERENCE_IMAGE_FILES {
        return Err(ReferenceImageError::TooManyImages);
    }

    let mut image_paths = Vec::new();
    let mut pdf_paths = Vec::new();
    let mut kinds = Vec::with_capacity(paths.len());
    for path in paths {
        let extension = path
            .extension()
            .and_then(|value| value.to_str())
            .unwrap_or_default()
            .to_ascii_lowercase();
        match extension.as_str() {
            "png" | "jpg" | "jpeg" => {
                image_paths.push(path.clone());
                kinds.push(AssetKind::Image);
            }
            "pdf" => {
                pdf_paths.push(path.clone());
                kinds.push(AssetKind::Pdf);
            }
            _ => return Err(ReferenceImageError::UnsupportedExtension),
        }
    }

    let images = if image_paths.is_empty() {
        Vec::new()
    } else {
        stage_reference_images(&image_paths, store)?
    };
    let pdfs = if pdf_paths.is_empty() {
        Vec::new()
    } else {
        match stage_reference_pdfs(&pdf_paths, store) {
            Ok(pdfs) => pdfs,
            Err(error) => {
                discard_staged_images(store, &images)?;
                return Err(error);
            }
        }
    };
    let total_bytes = images
        .iter()
        .map(|image| image.byte_length as u64)
        .chain(pdfs.iter().map(|pdf| pdf.byte_length as u64))
        .sum::<u64>();
    if total_bytes > MAX_REFERENCE_SET_BYTES {
        discard_staged_assets(store, &images, &pdfs)?;
        return Err(ReferenceImageError::SetTooLarge);
    }

    let mut image_index = 0;
    let mut pdf_index = 0;
    let order = kinds
        .into_iter()
        .map(|kind| match kind {
            AssetKind::Image => {
                let id = images[image_index].id.clone();
                image_index += 1;
                id
            }
            AssetKind::Pdf => {
                let id = pdfs[pdf_index].id.clone();
                pdf_index += 1;
                id
            }
        })
        .collect();

    Ok(StagedReferenceAssets {
        images,
        pdfs,
        order,
    })
}

fn discard_staged_images(
    store: &Path,
    images: &[StagedReferenceImage],
) -> Result<(), ReferenceImageError> {
    let ids = images
        .iter()
        .map(|image| image.id.clone())
        .collect::<Vec<_>>();
    remove_reference_images(store, &ids)
}

fn discard_staged_assets(
    store: &Path,
    images: &[StagedReferenceImage],
    pdfs: &[StagedReferencePdf],
) -> Result<(), ReferenceImageError> {
    let ids = images
        .iter()
        .map(|image| image.id.clone())
        .chain(pdfs.iter().map(|pdf| pdf.id.clone()))
        .collect::<Vec<_>>();
    remove_reference_images(store, &ids)
}

#[cfg(test)]
mod tests {
    use std::{fs, path::PathBuf};

    use tempfile::tempdir;

    use super::stage_reference_assets;

    fn png_header() -> Vec<u8> {
        let mut bytes = b"\x89PNG\r\n\x1a\n".to_vec();
        bytes.extend_from_slice(&13_u32.to_be_bytes());
        bytes.extend_from_slice(b"IHDR");
        bytes.extend_from_slice(&1_u32.to_be_bytes());
        bytes.extend_from_slice(&1_u32.to_be_bytes());
        bytes.extend_from_slice(&[8, 2, 0, 0, 0, 0, 0, 0, 0]);
        bytes
    }

    #[test]
    fn preserves_mixed_input_order_while_staging_managed_assets() {
        let root = tempdir().expect("temporary root");
        let image = root.path().join("scan.png");
        let pdf = root.path().join("score.pdf");
        let store = root.path().join("cache");
        fs::write(&image, png_header()).expect("write image");
        fs::write(&pdf, b"%PDF-1.7\nfixture").expect("write PDF");

        let staged = stage_reference_assets(&[pdf, image], &store).expect("stage mixed files");

        assert_eq!(staged.images.len(), 1);
        assert_eq!(staged.pdfs.len(), 1);
        assert!(staged.images[0].id.starts_with("img-"));
        assert!(staged.pdfs[0].id.starts_with("pdf-"));
        assert_eq!(
            staged.order,
            [staged.pdfs[0].id.clone(), staged.images[0].id.clone()]
        );
        assert_eq!(fs::read_dir(store).expect("list assets").count(), 2);
    }

    #[test]
    fn rolls_back_images_when_pdf_staging_fails() {
        let root = tempdir().expect("temporary root");
        let image = root.path().join("scan.png");
        let invalid_pdf = root.path().join("broken.pdf");
        let store = root.path().join("cache");
        fs::write(&image, png_header()).expect("write image");
        fs::write(&invalid_pdf, b"not a PDF").expect("write invalid PDF");

        assert!(stage_reference_assets(&[image, invalid_pdf], &store).is_err());
        assert_eq!(fs::read_dir(store).expect("list assets").count(), 0);
    }

    #[test]
    fn rejects_empty_overlarge_and_unsupported_batches_before_staging() {
        let root = tempdir().expect("temporary root");
        let store = root.path().join("cache");
        assert!(stage_reference_assets(&[], &store).is_err());
        let too_many = vec![PathBuf::from("unused.png"); 201];
        assert!(stage_reference_assets(&too_many, &store).is_err());
        assert!(stage_reference_assets(&[PathBuf::from("notes.txt")], &store).is_err());
        assert!(!store.exists());
    }
}
