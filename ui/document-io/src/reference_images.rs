use std::fs::{self, File};
use std::io::{self, Read, Write};
use std::path::{Path, PathBuf};

use tempfile::Builder;

pub const MAX_REFERENCE_IMAGE_BYTES: usize = 100 * 1024 * 1024;
pub const MAX_REFERENCE_IMAGE_PIXELS: u64 = 40_000_000;
pub const MAX_REFERENCE_SET_BYTES: u64 = 500 * 1024 * 1024;
pub const MAX_REFERENCE_IMAGE_FILES: usize = 200;
pub const MAX_REFERENCE_CACHE_BYTES: u64 = 2 * MAX_REFERENCE_SET_BYTES;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct StagedReferenceImage {
    pub id: String,
    pub path: PathBuf,
    pub name: String,
    pub mime_type: &'static str,
    pub byte_length: usize,
    pub width: u32,
    pub height: u32,
    pub orientation: u8,
}

#[derive(Debug)]
pub enum ReferenceImageError {
    Io(io::Error),
    InvalidStore,
    InvalidTarget,
    EmptyBatch,
    TooManyImages,
    CacheTooLarge,
    UnsupportedExtension,
    InvalidImage,
    DimensionsTooLarge,
    TooLarge,
    SetTooLarge,
    InvalidAssetId,
    UnsupportedPdfExtension,
    InvalidPdf,
    PdfTooLarge,
    PdfSetTooLarge,
}

impl std::fmt::Display for ReferenceImageError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Io(error) => write!(formatter, "reference import failed: {error}"),
            Self::InvalidStore => formatter.write_str("image cache directory is unavailable"),
            Self::InvalidTarget => formatter.write_str("selected reference is not a regular file"),
            Self::EmptyBatch => formatter.write_str("no reference files were selected"),
            Self::TooManyImages => formatter.write_str("reference file count exceeds 200"),
            Self::CacheTooLarge => formatter.write_str("reference cache exceeds 1 GiB"),
            Self::UnsupportedExtension => {
                formatter.write_str("only PNG, JPEG, and PDF references are supported")
            }
            Self::InvalidImage => formatter.write_str("file is not a valid PNG or JPEG image"),
            Self::DimensionsTooLarge => formatter.write_str("image exceeds the 40-megapixel limit"),
            Self::TooLarge => formatter.write_str("image exceeds the 100 MiB file limit"),
            Self::SetTooLarge => formatter.write_str("reference files exceed the 500 MiB limit"),
            Self::InvalidAssetId => formatter.write_str("managed reference ID is invalid"),
            Self::UnsupportedPdfExtension => {
                formatter.write_str("only PDF documents are supported")
            }
            Self::InvalidPdf => formatter.write_str("file is not a valid PDF document"),
            Self::PdfTooLarge => formatter.write_str("PDF exceeds the 100 MiB file limit"),
            Self::PdfSetTooLarge => formatter.write_str("PDF documents exceed the 500 MiB limit"),
        }
    }
}

impl std::error::Error for ReferenceImageError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        match self {
            Self::Io(error) => Some(error),
            Self::InvalidStore
            | Self::InvalidTarget
            | Self::EmptyBatch
            | Self::TooManyImages
            | Self::CacheTooLarge
            | Self::UnsupportedExtension
            | Self::InvalidImage
            | Self::DimensionsTooLarge
            | Self::TooLarge
            | Self::SetTooLarge
            | Self::InvalidAssetId
            | Self::UnsupportedPdfExtension
            | Self::InvalidPdf
            | Self::PdfTooLarge
            | Self::PdfSetTooLarge => None,
        }
    }
}

impl From<io::Error> for ReferenceImageError {
    fn from(error: io::Error) -> Self {
        Self::Io(error)
    }
}

#[derive(Clone, Copy)]
struct ImageInfo {
    mime_type: &'static str,
    suffix: &'static str,
    width: u32,
    height: u32,
    orientation: u8,
}

pub fn stage_reference_images(
    paths: &[PathBuf],
    store: &Path,
) -> Result<Vec<StagedReferenceImage>, ReferenceImageError> {
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
    let mut batch_bytes = 0;
    for path in paths {
        match stage_one(path, store, &mut total_bytes, &mut batch_bytes) {
            Ok(image) => staged.push(image),
            Err(error) => {
                let ids: Vec<_> = staged
                    .iter()
                    .map(|image: &StagedReferenceImage| image.id.clone())
                    .collect();
                let _ = remove_reference_images(store, &ids);
                return Err(error);
            }
        }
    }
    Ok(staged)
}

pub fn resolve_reference_image_paths(
    store: &Path,
    ids: &[String],
) -> Result<Vec<(String, PathBuf)>, ReferenceImageError> {
    if ids.len() > MAX_REFERENCE_IMAGE_FILES {
        return Err(ReferenceImageError::TooManyImages);
    }
    for id in ids {
        validate_asset_id(id)?;
    }
    match fs::symlink_metadata(store) {
        Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(Vec::new()),
        Err(error) => return Err(ReferenceImageError::Io(error)),
        Ok(metadata) if !metadata.is_dir() || metadata.file_type().is_symlink() => {
            return Err(ReferenceImageError::InvalidStore)
        }
        Ok(_) => {}
    }
    let mut resolved = Vec::with_capacity(ids.len());
    for id in ids {
        let path = store.join(id);
        match fs::symlink_metadata(&path) {
            Ok(metadata) if metadata.file_type().is_file() => {
                resolved.push((id.clone(), path));
            }
            Ok(_) => return Err(ReferenceImageError::InvalidTarget),
            Err(error) if error.kind() == io::ErrorKind::NotFound => {}
            Err(error) => return Err(ReferenceImageError::Io(error)),
        }
    }
    Ok(resolved)
}

fn stage_one(
    source: &Path,
    store: &Path,
    total_bytes: &mut u64,
    batch_bytes: &mut u64,
) -> Result<StagedReferenceImage, ReferenceImageError> {
    ensure_supported_extension(source)?;
    let file = File::open(source)?;
    let metadata = file.metadata()?;
    if !metadata.is_file() {
        return Err(ReferenceImageError::InvalidTarget);
    }
    if metadata.len() > MAX_REFERENCE_IMAGE_BYTES as u64 {
        return Err(ReferenceImageError::TooLarge);
    }
    let mut bytes = Vec::new();
    Read::take(file, MAX_REFERENCE_IMAGE_BYTES as u64 + 1).read_to_end(&mut bytes)?;
    if bytes.len() > MAX_REFERENCE_IMAGE_BYTES {
        return Err(ReferenceImageError::TooLarge);
    }
    let info = inspect_image(&bytes)?;
    if u64::from(info.width) * u64::from(info.height) > MAX_REFERENCE_IMAGE_PIXELS {
        return Err(ReferenceImageError::DimensionsTooLarge);
    }
    *batch_bytes = size_within_limit(*batch_bytes, bytes.len(), MAX_REFERENCE_SET_BYTES)
        .ok_or(ReferenceImageError::SetTooLarge)?;
    *total_bytes = size_within_limit(*total_bytes, bytes.len(), MAX_REFERENCE_CACHE_BYTES)
        .ok_or(ReferenceImageError::CacheTooLarge)?;

    let name = source
        .file_name()
        .and_then(|name| name.to_str())
        .ok_or(ReferenceImageError::InvalidTarget)?
        .to_owned();
    let mut temporary = Builder::new()
        .prefix("img-")
        .suffix(info.suffix)
        .tempfile_in(store)?;
    temporary.write_all(&bytes)?;
    temporary.as_file().sync_all()?;
    let (_, path) = temporary
        .keep()
        .map_err(|error| ReferenceImageError::Io(error.error))?;
    let id = path
        .file_name()
        .and_then(|name| name.to_str())
        .ok_or(ReferenceImageError::InvalidAssetId)?
        .to_owned();
    Ok(StagedReferenceImage {
        id,
        path,
        name,
        mime_type: info.mime_type,
        byte_length: bytes.len(),
        width: info.width,
        height: info.height,
        orientation: info.orientation,
    })
}

fn size_within_limit(total: u64, size: usize, limit: u64) -> Option<u64> {
    let total = total.checked_add(u64::try_from(size).ok()?)?;
    (total <= limit).then_some(total)
}

pub fn remove_reference_images(store: &Path, ids: &[String]) -> Result<(), ReferenceImageError> {
    for id in ids {
        validate_asset_id(id)?;
    }
    match fs::symlink_metadata(store) {
        Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(()),
        Err(error) => return Err(ReferenceImageError::Io(error)),
        Ok(metadata) if !metadata.is_dir() || metadata.file_type().is_symlink() => {
            return Err(ReferenceImageError::InvalidStore)
        }
        Ok(_) => {}
    }
    for id in ids {
        let path = store.join(id);
        match fs::symlink_metadata(&path) {
            Ok(metadata) if metadata.file_type().is_file() => {}
            Ok(_) => return Err(ReferenceImageError::InvalidTarget),
            Err(error) if error.kind() == io::ErrorKind::NotFound => {}
            Err(error) => return Err(ReferenceImageError::Io(error)),
        }
    }
    for id in ids {
        match fs::remove_file(store.join(id)) {
            Ok(()) => {}
            Err(error) if error.kind() == io::ErrorKind::NotFound => {}
            Err(error) => return Err(ReferenceImageError::Io(error)),
        }
    }
    Ok(())
}

pub fn prune_reference_images(
    store: &Path,
    retained_ids: &[String],
) -> Result<(), ReferenceImageError> {
    for id in retained_ids {
        validate_asset_id(id)?;
    }
    match fs::symlink_metadata(store) {
        Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(()),
        Err(error) => return Err(ReferenceImageError::Io(error)),
        Ok(metadata) if !metadata.is_dir() || metadata.file_type().is_symlink() => {
            return Err(ReferenceImageError::InvalidStore)
        }
        Ok(_) => {}
    }
    let retained: std::collections::HashSet<_> = retained_ids.iter().map(String::as_str).collect();
    for entry in fs::read_dir(store)? {
        let entry = entry?;
        let Some(id) = entry.file_name().to_str().map(str::to_owned) else {
            continue;
        };
        if !is_managed_asset_id(&id) {
            continue;
        }
        let file_type = entry.file_type()?;
        if file_type.is_symlink() || (file_type.is_file() && !retained.contains(id.as_str())) {
            fs::remove_file(entry.path())?;
        }
    }
    Ok(())
}

pub(super) fn ensure_store(store: &Path) -> Result<(), ReferenceImageError> {
    match fs::symlink_metadata(store) {
        Ok(metadata) if metadata.is_dir() && !metadata.file_type().is_symlink() => Ok(()),
        Ok(_) => Err(ReferenceImageError::InvalidStore),
        Err(error) if error.kind() == io::ErrorKind::NotFound => {
            fs::create_dir_all(store)?;
            ensure_store(store)
        }
        Err(error) => Err(ReferenceImageError::Io(error)),
    }
}

pub(super) fn managed_store_size(store: &Path) -> Result<(u64, usize), ReferenceImageError> {
    let mut bytes = 0_u64;
    let mut count = 0_usize;
    for entry in fs::read_dir(store)? {
        let entry = entry?;
        let Some(id) = entry.file_name().to_str().map(str::to_owned) else {
            continue;
        };
        if is_managed_asset_id(&id) && entry.file_type()?.is_file() {
            bytes = bytes.saturating_add(entry.metadata()?.len());
            count = count.saturating_add(1);
        }
    }
    if bytes > MAX_REFERENCE_CACHE_BYTES {
        return Err(ReferenceImageError::CacheTooLarge);
    }
    Ok((bytes, count))
}

fn ensure_supported_extension(path: &Path) -> Result<(), ReferenceImageError> {
    let extension = path
        .extension()
        .and_then(|extension| extension.to_str())
        .ok_or(ReferenceImageError::UnsupportedExtension)?
        .to_ascii_lowercase();
    if matches!(extension.as_str(), "png" | "jpg" | "jpeg") {
        Ok(())
    } else {
        Err(ReferenceImageError::UnsupportedExtension)
    }
}

fn validate_asset_id(id: &str) -> Result<(), ReferenceImageError> {
    if is_managed_asset_id(id) {
        Ok(())
    } else {
        Err(ReferenceImageError::InvalidAssetId)
    }
}

pub(super) fn is_managed_asset_id(id: &str) -> bool {
    let Some((kind, stem)) = id.split_once('-') else {
        return false;
    };
    let Some((random, extension)) = stem.rsplit_once('.') else {
        return false;
    };
    let extension_allowed = match kind {
        "img" => matches!(extension, "png" | "jpg"),
        "pdf" => extension == "pdf",
        _ => false,
    };
    !random.is_empty()
        && random.bytes().all(|byte| byte.is_ascii_alphanumeric())
        && extension_allowed
}

fn inspect_image(bytes: &[u8]) -> Result<ImageInfo, ReferenceImageError> {
    if bytes.starts_with(b"\x89PNG\r\n\x1a\n") {
        inspect_png(bytes)
    } else if bytes.starts_with(b"\xff\xd8") {
        inspect_jpeg(bytes)
    } else {
        Err(ReferenceImageError::InvalidImage)
    }
}

fn inspect_png(bytes: &[u8]) -> Result<ImageInfo, ReferenceImageError> {
    if bytes.len() < 24 || read_u32_be(bytes, 8) != Some(13) || bytes.get(12..16) != Some(b"IHDR") {
        return Err(ReferenceImageError::InvalidImage);
    }
    let width = read_u32_be(bytes, 16).ok_or(ReferenceImageError::InvalidImage)?;
    let height = read_u32_be(bytes, 20).ok_or(ReferenceImageError::InvalidImage)?;
    if width == 0 || height == 0 {
        return Err(ReferenceImageError::InvalidImage);
    }
    let mut orientation = 1;
    let mut offset = 8_usize;
    while let Some(length) = read_u32_be(bytes, offset).map(|length| length as usize) {
        let Some(data_start) = offset.checked_add(8) else {
            break;
        };
        let Some(data_end) = data_start.checked_add(length) else {
            break;
        };
        let Some(next) = data_end.checked_add(4) else {
            break;
        };
        if next > bytes.len() {
            break;
        }
        match bytes.get(offset + 4..offset + 8) {
            Some(b"eXIf") => {
                orientation = tiff_orientation(&bytes[data_start..data_end]).unwrap_or(1);
            }
            Some(b"IDAT") | Some(b"IEND") => break,
            _ => {}
        }
        offset = next;
    }
    Ok(ImageInfo {
        mime_type: "image/png",
        suffix: ".png",
        width,
        height,
        orientation,
    })
}

fn inspect_jpeg(bytes: &[u8]) -> Result<ImageInfo, ReferenceImageError> {
    let mut offset = 2_usize;
    let mut dimensions = None;
    let mut orientation = 1;
    while offset < bytes.len() {
        if bytes.get(offset) != Some(&0xff) {
            return Err(ReferenceImageError::InvalidImage);
        }
        while bytes.get(offset) == Some(&0xff) {
            offset += 1;
        }
        let marker = *bytes.get(offset).ok_or(ReferenceImageError::InvalidImage)?;
        offset += 1;
        if marker == 0xd9 || marker == 0xda {
            break;
        }
        if marker == 0x01 || (0xd0..=0xd8).contains(&marker) {
            continue;
        }
        let length =
            usize::from(read_u16_be(bytes, offset).ok_or(ReferenceImageError::InvalidImage)?);
        if length < 2 {
            return Err(ReferenceImageError::InvalidImage);
        }
        let data_start = offset + 2;
        let data_end = offset
            .checked_add(length)
            .filter(|end| *end <= bytes.len())
            .ok_or(ReferenceImageError::InvalidImage)?;
        let segment = &bytes[data_start..data_end];
        if marker == 0xe1 && segment.starts_with(b"Exif\0\0") {
            orientation = tiff_orientation(&segment[6..]).unwrap_or(1);
        }
        if is_start_of_frame(marker) && segment.len() >= 5 {
            let height = read_u16_be(segment, 1).ok_or(ReferenceImageError::InvalidImage)?;
            let width = read_u16_be(segment, 3).ok_or(ReferenceImageError::InvalidImage)?;
            if width == 0 || height == 0 {
                return Err(ReferenceImageError::InvalidImage);
            }
            dimensions = Some((u32::from(width), u32::from(height)));
        }
        offset = data_end;
    }
    let (width, height) = dimensions.ok_or(ReferenceImageError::InvalidImage)?;
    Ok(ImageInfo {
        mime_type: "image/jpeg",
        suffix: ".jpg",
        width,
        height,
        orientation,
    })
}

fn is_start_of_frame(marker: u8) -> bool {
    matches!(marker, 0xc0..=0xc3 | 0xc5..=0xc7 | 0xc9..=0xcb | 0xcd..=0xcf)
}

fn tiff_orientation(bytes: &[u8]) -> Option<u8> {
    let little_endian = match bytes.get(..2)? {
        b"II" => true,
        b"MM" => false,
        _ => return None,
    };
    let read_u16 = |offset: usize| {
        let value = bytes.get(offset..offset.checked_add(2)?)?;
        Some(if little_endian {
            u16::from_le_bytes([value[0], value[1]])
        } else {
            u16::from_be_bytes([value[0], value[1]])
        })
    };
    let read_u32 = |offset: usize| {
        let value = bytes.get(offset..offset.checked_add(4)?)?;
        Some(if little_endian {
            u32::from_le_bytes([value[0], value[1], value[2], value[3]])
        } else {
            u32::from_be_bytes([value[0], value[1], value[2], value[3]])
        })
    };
    if read_u16(2)? != 42 {
        return None;
    }
    let directory = usize::try_from(read_u32(4)?).ok()?;
    let entries = usize::from(read_u16(directory)?);
    for index in 0..entries {
        let entry = directory.checked_add(2 + index.checked_mul(12)?)?;
        if read_u16(entry)? == 0x0112
            && read_u16(entry.checked_add(2)?)? == 3
            && read_u32(entry.checked_add(4)?)? == 1
        {
            return match read_u16(entry.checked_add(8)?)? {
                orientation @ 1..=8 => Some(orientation as u8),
                _ => None,
            };
        }
    }
    None
}

fn read_u16_be(bytes: &[u8], offset: usize) -> Option<u16> {
    Some(u16::from_be_bytes(
        bytes.get(offset..offset.checked_add(2)?)?.try_into().ok()?,
    ))
}

fn read_u32_be(bytes: &[u8], offset: usize) -> Option<u32> {
    Some(u32::from_be_bytes(
        bytes.get(offset..offset.checked_add(4)?)?.try_into().ok()?,
    ))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn png_header(width: u32, height: u32) -> Vec<u8> {
        let mut bytes = b"\x89PNG\r\n\x1a\n".to_vec();
        bytes.extend_from_slice(&13_u32.to_be_bytes());
        bytes.extend_from_slice(b"IHDR");
        bytes.extend_from_slice(&width.to_be_bytes());
        bytes.extend_from_slice(&height.to_be_bytes());
        bytes.extend_from_slice(&[8, 2, 0, 0, 0]);
        bytes.extend_from_slice(&[0; 4]);
        bytes
    }

    fn jpeg_header(width: u16, height: u16) -> Vec<u8> {
        let mut bytes = b"\xff\xd8\xff\xc0\x00\x0b\x08".to_vec();
        bytes.extend_from_slice(&height.to_be_bytes());
        bytes.extend_from_slice(&width.to_be_bytes());
        bytes.extend_from_slice(&[1, 1, 0x11, 0]);
        bytes.extend_from_slice(b"\xff\xd9");
        bytes
    }

    #[test]
    fn detects_image_type_from_signature_and_reads_dimensions() {
        let png = inspect_image(&png_header(640, 480)).expect("inspect PNG header");
        assert_eq!(
            (png.mime_type, png.width, png.height, png.orientation),
            ("image/png", 640, 480, 1)
        );

        let jpeg = inspect_image(&jpeg_header(800, 600)).expect("inspect JPEG header");
        assert_eq!(
            (jpeg.mime_type, jpeg.width, jpeg.height),
            ("image/jpeg", 800, 600)
        );
    }

    #[test]
    fn batch_stages_managed_copies_and_rolls_back_on_invalid_later_file() {
        let root = tempfile::tempdir().expect("temporary root");
        let store = root.path().join("reference-images");
        let valid = root.path().join("scan.PNG");
        let invalid = root.path().join("bad.jpg");
        fs::write(&valid, png_header(1, 1)).expect("write PNG header");
        fs::write(&invalid, b"not an image").expect("write invalid image");

        assert!(stage_reference_images(&[valid.clone(), invalid], &store).is_err());
        assert_eq!(fs::read_dir(&store).expect("list staged images").count(), 0);

        let staged =
            stage_reference_images(std::slice::from_ref(&valid), &store).expect("stage image");
        assert_eq!(staged[0].mime_type, "image/png");
        assert_eq!(staged[0].name, "scan.PNG");
        assert_eq!(
            fs::read(&staged[0].path).expect("read staged copy"),
            fs::read(valid).unwrap()
        );
        assert!(staged[0].id.starts_with("img-") && staged[0].id.ends_with(".png"));
        assert_eq!(
            resolve_reference_image_paths(&store, std::slice::from_ref(&staged[0].id))
                .expect("resolve staged ID"),
            vec![(staged[0].id.clone(), staged[0].path.clone())]
        );
        prune_reference_images(&store, &[]).expect("prune unused copy");
        assert_eq!(fs::read_dir(&store).expect("list pruned images").count(), 0);
    }

    #[test]
    fn validates_extension_limits_dimensions_ids_and_safe_pruning() {
        let root = tempfile::tempdir().expect("temporary root");
        let store = root.path().join("reference-images");
        let oversized = root.path().join("oversized.jpg");
        File::create(&oversized)
            .expect("create oversized image")
            .set_len(MAX_REFERENCE_IMAGE_BYTES as u64 + 1)
            .expect("extend oversized image");
        assert!(matches!(
            stage_reference_images(std::slice::from_ref(&oversized), &store),
            Err(ReferenceImageError::TooLarge)
        ));

        let too_large = root.path().join("large.png");
        fs::write(&too_large, png_header(40_000, 1_001)).expect("write large PNG header");
        assert!(matches!(
            stage_reference_images(&[too_large], &store),
            Err(ReferenceImageError::DimensionsTooLarge)
        ));
        assert!(matches!(
            remove_reference_images(&store, &["../outside.png".into()]),
            Err(ReferenceImageError::InvalidAssetId)
        ));

        let staged = stage_reference_images(&[root.path().join("large.txt")], &store);
        assert!(matches!(
            staged,
            Err(ReferenceImageError::UnsupportedExtension)
        ));
    }

    #[test]
    fn managed_asset_prefixes_match_their_file_types() {
        assert!(is_managed_asset_id("img-Ab12.png"));
        assert!(is_managed_asset_id("img-Ab12.jpg"));
        assert!(is_managed_asset_id("pdf-Ab12.pdf"));
        assert!(!is_managed_asset_id("pdf-Ab12.png"));
        assert!(!is_managed_asset_id("img-Ab12.pdf"));
        assert!(!is_managed_asset_id("other-Ab12.pdf"));
    }

    #[test]
    fn tiff_orientation_parser_handles_endian_and_invalid_values() {
        let little = [
            b'I', b'I', 42, 0, 8, 0, 0, 0, 1, 0, 0x12, 0x01, 3, 0, 1, 0, 0, 0, 6, 0, 0, 0,
        ];
        assert_eq!(tiff_orientation(&little), Some(6));
        assert_eq!(tiff_orientation(b"not TIFF"), None);
        assert_eq!(
            tiff_orientation(&[b'I', b'I', 42, 0, 255, 255, 255, 255]),
            None
        );
    }

    #[test]
    fn image_batch_and_managed_cache_sizes_are_bounded_without_overflow() {
        assert_eq!(size_within_limit(400, 100, 500), Some(500));
        assert_eq!(size_within_limit(500, 1, 500), None);
        assert_eq!(size_within_limit(u64::MAX, 1, u64::MAX), None);
    }
}
