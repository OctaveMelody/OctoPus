use std::collections::VecDeque;
use std::fs::{self, File};
use std::io::{self, Read, Write};
use std::path::{Component, Path, PathBuf};
use std::sync::{Arc, Mutex};

use tempfile::NamedTempFile;

pub mod file_exports;
pub mod reference_assets;
pub mod reference_images;
pub mod reference_pdfs;
pub mod reference_recovery;
pub mod score_exports;
pub mod svg_exports;

pub const MAX_JPS_FILE_BYTES: usize = 8 * 1024 * 1024;
pub const MAX_RECOVERY_SNAPSHOT_BYTES: usize = 40 * 1024 * 1024;
pub const MAX_SELECTED_JPS_FILES: usize = 16;

#[derive(Clone, Default)]
pub struct RecoverySnapshotSequence(Arc<Mutex<u64>>);

impl RecoverySnapshotSequence {
    pub fn write_if_newer(
        &self,
        path: &Path,
        sequence: u64,
        text: Option<&str>,
    ) -> Result<bool, DocumentIoError> {
        let mut latest = self
            .0
            .lock()
            .map_err(|_| DocumentIoError::RecoverySequenceUnavailable)?;
        if sequence <= *latest {
            return Ok(false);
        }
        *latest = sequence;
        match text {
            Some(text) => write_recovery_snapshot_atomically(path, text)?,
            None => remove_recovery_snapshot(path)?,
        }
        Ok(true)
    }
}

#[derive(Default)]
pub struct SelectedJpsFiles(Mutex<VecDeque<PathBuf>>);

impl SelectedJpsFiles {
    pub fn remember(&self, path: PathBuf) -> Result<(), String> {
        validate_jps_path(&path).map_err(|error| error.to_string())?;
        let mut paths = self
            .0
            .lock()
            .map_err(|_| "selected-file grant registry is unavailable".to_owned())?;
        if let Some(position) = paths.iter().position(|selected| selected == &path) {
            paths.remove(position);
        }
        paths.push_back(path);
        while paths.len() > MAX_SELECTED_JPS_FILES {
            paths.pop_front();
        }
        Ok(())
    }

    pub fn allows(&self, path: &Path) -> Result<bool, String> {
        let paths = self
            .0
            .lock()
            .map_err(|_| "selected-file grant registry is unavailable".to_owned())?;
        Ok(paths.iter().any(|selected| selected == path))
    }
}

#[derive(Debug)]
pub enum DocumentIoError {
    Io(io::Error),
    InvalidPath,
    InvalidUtf8,
    InvalidTarget,
    ChangedOnDisk,
    RecoveryTooLarge,
    RecoverySequenceUnavailable,
    WorkingCopyNameExhausted,
    EmptyExport,
    ExportTooLarge,
    TooManyExportFiles,
    InvalidExportPath,
    InvalidExportPage,
    UnsupportedExportFeature,
    ExportPageTooLarge,
    InvalidExportDpi,
    ExportConversionFailed,
    ExportDestinationExists,
    PartialExport { recovery_location: PathBuf },
    TooLarge,
    UnsupportedExtension,
}

impl std::fmt::Display for DocumentIoError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Io(error) => write!(formatter, "file operation failed: {error}"),
            Self::InvalidPath => formatter.write_str("file path is invalid"),
            Self::InvalidUtf8 => formatter.write_str("JPS source is not valid UTF-8"),
            Self::InvalidTarget => formatter.write_str("save target must be a regular file"),
            Self::ChangedOnDisk => {
                formatter.write_str("file changed outside the app; save was not applied")
            }
            Self::RecoveryTooLarge => formatter.write_str("recovery snapshot is too large"),
            Self::RecoverySequenceUnavailable => {
                formatter.write_str("recovery sequence is unavailable")
            }
            Self::WorkingCopyNameExhausted => {
                formatter.write_str("could not allocate a unique working-copy name")
            }
            Self::EmptyExport => formatter.write_str("export has no pages or empty content"),
            Self::ExportTooLarge => formatter.write_str("export exceeds the 64 MiB limit"),
            Self::TooManyExportFiles => formatter.write_str("export exceeds the 200-file limit"),
            Self::InvalidExportPath => formatter
                .write_str("export target must be an absolute path with the right extension"),
            Self::InvalidExportPage => formatter.write_str("SVG export page is invalid"),
            Self::UnsupportedExportFeature => {
                formatter.write_str("SVG export does not support embedded images or filters")
            }
            Self::ExportPageTooLarge => formatter.write_str("export page exceeds resource limits"),
            Self::InvalidExportDpi => formatter.write_str("JPG resolution must be 96 or 300 DPI"),
            Self::ExportConversionFailed => {
                formatter.write_str("could not convert an SVG export page")
            }
            Self::ExportDestinationExists => {
                formatter.write_str("one or more export destination files already exist")
            }
            Self::PartialExport { recovery_location } => write!(
                formatter,
                "export rollback was incomplete; inspect the destination and recover original files from {}",
                recovery_location.display()
            ),
            Self::TooLarge => write!(
                formatter,
                "JPS source exceeds the {MAX_JPS_FILE_BYTES}-byte limit"
            ),
            Self::UnsupportedExtension => formatter.write_str("only .jps files are supported"),
        }
    }
}

impl std::error::Error for DocumentIoError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        match self {
            Self::Io(error) => Some(error),
            Self::InvalidPath
            | Self::InvalidUtf8
            | Self::InvalidTarget
            | Self::ChangedOnDisk
            | Self::RecoveryTooLarge
            | Self::RecoverySequenceUnavailable
            | Self::WorkingCopyNameExhausted
            | Self::EmptyExport
            | Self::ExportTooLarge
            | Self::TooManyExportFiles
            | Self::InvalidExportPath
            | Self::InvalidExportPage
            | Self::UnsupportedExportFeature
            | Self::ExportPageTooLarge
            | Self::InvalidExportDpi
            | Self::ExportConversionFailed
            | Self::ExportDestinationExists
            | Self::PartialExport { .. }
            | Self::TooLarge
            | Self::UnsupportedExtension => None,
        }
    }
}

impl From<io::Error> for DocumentIoError {
    fn from(error: io::Error) -> Self {
        Self::Io(error)
    }
}

pub fn read_jps_text(path: &Path) -> Result<String, DocumentIoError> {
    validate_jps_path(path)?;
    let metadata = fs::metadata(path)?;
    if !metadata.is_file() {
        return Err(DocumentIoError::InvalidTarget);
    }
    if metadata.len() > MAX_JPS_FILE_BYTES as u64 {
        return Err(DocumentIoError::TooLarge);
    }

    let file = File::open(path)?;
    let metadata = file.metadata()?;
    if !metadata.is_file() {
        return Err(DocumentIoError::InvalidTarget);
    }
    if metadata.len() > MAX_JPS_FILE_BYTES as u64 {
        return Err(DocumentIoError::TooLarge);
    }

    let mut bytes = Vec::new();
    file.take(MAX_JPS_FILE_BYTES as u64 + 1)
        .read_to_end(&mut bytes)?;
    if bytes.len() > MAX_JPS_FILE_BYTES {
        return Err(DocumentIoError::TooLarge);
    }

    String::from_utf8(bytes).map_err(|_| DocumentIoError::InvalidUtf8)
}

pub fn read_recovery_snapshot(path: &Path) -> Result<Option<String>, DocumentIoError> {
    let metadata = match fs::symlink_metadata(path) {
        Ok(metadata) if metadata.file_type().is_file() => metadata,
        Ok(_) => return Err(DocumentIoError::InvalidTarget),
        Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(None),
        Err(error) => return Err(DocumentIoError::Io(error)),
    };
    if metadata.len() > MAX_RECOVERY_SNAPSHOT_BYTES as u64 {
        return Err(DocumentIoError::RecoveryTooLarge);
    }

    let file = File::open(path)?;
    if file.metadata()?.len() > MAX_RECOVERY_SNAPSHOT_BYTES as u64 {
        return Err(DocumentIoError::RecoveryTooLarge);
    }
    let mut bytes = Vec::new();
    file.take(MAX_RECOVERY_SNAPSHOT_BYTES as u64 + 1)
        .read_to_end(&mut bytes)?;
    if bytes.len() > MAX_RECOVERY_SNAPSHOT_BYTES {
        return Err(DocumentIoError::RecoveryTooLarge);
    }
    String::from_utf8(bytes)
        .map(Some)
        .map_err(|_| DocumentIoError::InvalidUtf8)
}

pub fn write_recovery_snapshot_atomically(path: &Path, text: &str) -> Result<(), DocumentIoError> {
    if text.len() > MAX_RECOVERY_SNAPSHOT_BYTES {
        return Err(DocumentIoError::RecoveryTooLarge);
    }
    let parent = path
        .parent()
        .filter(|parent| !parent.as_os_str().is_empty())
        .unwrap_or_else(|| Path::new("."));
    fs::create_dir_all(parent)?;
    match fs::symlink_metadata(path) {
        Ok(metadata) if metadata.file_type().is_file() => {}
        Ok(_) => return Err(DocumentIoError::InvalidTarget),
        Err(error) if error.kind() == io::ErrorKind::NotFound => {}
        Err(error) => return Err(DocumentIoError::Io(error)),
    }

    let mut temporary = NamedTempFile::new_in(parent)?;
    temporary.write_all(text.as_bytes())?;
    temporary.as_file().sync_all()?;
    temporary
        .persist(path)
        .map_err(|error| DocumentIoError::Io(error.error))?;
    Ok(())
}

pub fn remove_recovery_snapshot(path: &Path) -> Result<(), DocumentIoError> {
    match fs::symlink_metadata(path) {
        Ok(metadata) if metadata.file_type().is_file() => fs::remove_file(path)?,
        Ok(_) => return Err(DocumentIoError::InvalidTarget),
        Err(error) if error.kind() == io::ErrorKind::NotFound => {}
        Err(error) => return Err(DocumentIoError::Io(error)),
    }
    Ok(())
}

pub fn write_jps_text_atomically(path: &Path, text: &str) -> Result<(), DocumentIoError> {
    write_jps_text(path, text, None, true)
}

pub fn write_new_jps_text_atomically(path: &Path, text: &str) -> Result<(), DocumentIoError> {
    write_jps_text(path, text, None, false)
}

pub fn write_jps_text_atomically_if_unchanged(
    path: &Path,
    expected_text: &str,
    text: &str,
) -> Result<(), DocumentIoError> {
    write_jps_text(path, text, Some(expected_text), true)
}

fn write_jps_text(
    path: &Path,
    text: &str,
    expected_text: Option<&str>,
    replace_existing: bool,
) -> Result<(), DocumentIoError> {
    validate_jps_path(path)?;
    if text.len() > MAX_JPS_FILE_BYTES {
        return Err(DocumentIoError::TooLarge);
    }

    let existing = match fs::symlink_metadata(path) {
        Ok(metadata) if metadata.file_type().is_file() => Some(metadata),
        Ok(_) => return Err(DocumentIoError::InvalidTarget),
        Err(error) if error.kind() == io::ErrorKind::NotFound => None,
        Err(error) => return Err(DocumentIoError::Io(error)),
    };
    if existing.is_some() && !replace_existing {
        return Err(DocumentIoError::ChangedOnDisk);
    }
    let parent = path
        .parent()
        .filter(|parent| !parent.as_os_str().is_empty())
        .unwrap_or_else(|| Path::new("."));
    let mut temporary = NamedTempFile::new_in(parent)?;
    temporary.write_all(text.as_bytes())?;
    if let Some(metadata) = existing {
        temporary
            .as_file()
            .set_permissions(metadata.permissions())?;
    }
    temporary.as_file().sync_all()?;
    if let Some(expected_text) = expected_text {
        if read_jps_text(path)? != expected_text {
            return Err(DocumentIoError::ChangedOnDisk);
        }
    }
    let result = if replace_existing {
        temporary.persist(path)
    } else {
        temporary.persist_noclobber(path)
    };
    result.map_err(|error| DocumentIoError::Io(error.error))?;
    Ok(())
}

pub fn validate_jps_path(path: &Path) -> Result<PathBuf, DocumentIoError> {
    if !path.is_absolute()
        || path.file_name().is_none()
        || path.to_string_lossy().len() > 32 * 1024
        || path
            .components()
            .any(|component| component == Component::ParentDir)
    {
        return Err(DocumentIoError::InvalidPath);
    }
    if !path
        .extension()
        .and_then(|extension| extension.to_str())
        .is_some_and(|extension| extension.eq_ignore_ascii_case("jps"))
    {
        return Err(DocumentIoError::UnsupportedExtension);
    }
    Ok(path.to_path_buf())
}

pub fn list_jps_examples(directory: &Path) -> Result<Vec<String>, DocumentIoError> {
    let mut names = Vec::new();
    for entry in fs::read_dir(directory)? {
        let entry = entry?;
        if !entry.file_type()?.is_file() {
            continue;
        }
        let path = entry.path();
        if !path
            .extension()
            .and_then(|extension| extension.to_str())
            .is_some_and(|extension| extension.eq_ignore_ascii_case("jps"))
        {
            continue;
        }
        if let Some(name) = path.file_name().and_then(|name| name.to_str()) {
            names.push(name.to_owned());
        }
    }
    names.sort_by_key(|name| name.to_lowercase());
    Ok(names)
}

pub fn read_jps_example(directory: &Path, name: &str) -> Result<String, DocumentIoError> {
    validate_catalog_name(name)?;
    let path = directory.join(name);
    let metadata = fs::symlink_metadata(&path)?;
    if !metadata.file_type().is_file() {
        return Err(DocumentIoError::InvalidTarget);
    }
    read_jps_text(&path)
}

pub fn create_jps_working_copy(
    directory: &Path,
    original_name: &str,
    text: &str,
) -> Result<PathBuf, DocumentIoError> {
    validate_catalog_name(original_name)?;
    if text.len() > MAX_JPS_FILE_BYTES {
        return Err(DocumentIoError::TooLarge);
    }
    fs::create_dir_all(directory)?;
    let path = Path::new(original_name);
    let stem = path
        .file_stem()
        .and_then(|stem| stem.to_str())
        .ok_or(DocumentIoError::InvalidPath)?;
    let extension = path
        .extension()
        .and_then(|extension| extension.to_str())
        .ok_or(DocumentIoError::UnsupportedExtension)?;

    for suffix in 1..=10_000 {
        let name = if suffix == 1 {
            original_name.to_owned()
        } else {
            format!("{stem} ({suffix}).{extension}")
        };
        let target = validate_jps_path(&directory.join(name))?;
        let mut temporary = NamedTempFile::new_in(directory)?;
        temporary.write_all(text.as_bytes())?;
        temporary.as_file().sync_all()?;
        match temporary.persist_noclobber(&target) {
            Ok(_) => return Ok(target),
            Err(error) if error.error.kind() == io::ErrorKind::AlreadyExists => {
                drop(error.file);
            }
            Err(error) => return Err(DocumentIoError::Io(error.error)),
        }
    }
    Err(DocumentIoError::WorkingCopyNameExhausted)
}

fn validate_catalog_name(name: &str) -> Result<(), DocumentIoError> {
    if name.is_empty()
        || name.len() > 255
        || name
            .chars()
            .any(|character| matches!(character, '/' | '\\' | '\0'))
        || Path::new(name).components().count() != 1
    {
        return Err(DocumentIoError::InvalidPath);
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use std::fs;

    use std::path::Path;

    use super::{
        create_jps_working_copy, list_jps_examples, read_jps_example, read_jps_text,
        read_recovery_snapshot, remove_recovery_snapshot, validate_jps_path,
        write_jps_text_atomically, write_jps_text_atomically_if_unchanged,
        write_new_jps_text_atomically, write_recovery_snapshot_atomically, DocumentIoError,
        RecoverySnapshotSequence, SelectedJpsFiles, MAX_JPS_FILE_BYTES,
        MAX_RECOVERY_SNAPSHOT_BYTES, MAX_SELECTED_JPS_FILES,
    };

    #[test]
    fn new_save_never_overwrites_a_file_created_after_the_dialog() {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("Existing.jps");
        write_new_jps_text_atomically(&path, "first score").unwrap();
        assert!(matches!(
            write_new_jps_text_atomically(&path, "unconfirmed replacement"),
            Err(DocumentIoError::ChangedOnDisk)
        ));
        assert_eq!(fs::read_to_string(&path).unwrap(), "first score");
        assert_eq!(fs::read_dir(directory.path()).unwrap().count(), 1);
    }

    #[test]
    fn read_preserves_bom_and_unicode() {
        let directory = tempfile::tempdir().expect("temporary directory");
        let path = directory.path().join("简谱 测试.jps");
        fs::write(&path, "\u{feff}简谱 Q: 1 2 3").expect("write source");

        assert_eq!(
            read_jps_text(&path).expect("read source"),
            "\u{feff}简谱 Q: 1 2 3"
        );
    }

    #[test]
    fn recovery_snapshot_is_atomic_bounded_and_removable() {
        let directory = tempfile::tempdir().expect("temporary directory");
        let path = directory.path().join("app/recovery.json");
        assert_eq!(read_recovery_snapshot(&path).unwrap(), None);

        write_recovery_snapshot_atomically(&path, "{\"version\":1,\"title\":\"简谱\"}")
            .expect("write recovery snapshot");
        assert_eq!(
            read_recovery_snapshot(&path).unwrap().as_deref(),
            Some("{\"version\":1,\"title\":\"简谱\"}")
        );
        assert_eq!(fs::read_dir(path.parent().unwrap()).unwrap().count(), 1);

        remove_recovery_snapshot(&path).expect("remove recovery snapshot");
        remove_recovery_snapshot(&path).expect("remove missing recovery snapshot");
        assert_eq!(read_recovery_snapshot(&path).unwrap(), None);
    }

    #[test]
    fn recovery_snapshot_rejects_oversized_content_without_replacing_existing_data() {
        let directory = tempfile::tempdir().expect("temporary directory");
        let path = directory.path().join("recovery.json");
        write_recovery_snapshot_atomically(&path, "previous snapshot")
            .expect("write previous snapshot");

        assert!(matches!(
            write_recovery_snapshot_atomically(&path, &"0".repeat(MAX_RECOVERY_SNAPSHOT_BYTES + 1)),
            Err(DocumentIoError::RecoveryTooLarge)
        ));
        assert_eq!(fs::read_to_string(path).unwrap(), "previous snapshot");
    }

    #[cfg(unix)]
    #[test]
    fn recovery_snapshot_refuses_symlink_targets() {
        let directory = tempfile::tempdir().expect("temporary directory");
        let target = directory.path().join("target.json");
        let link = directory.path().join("recovery.json");
        fs::write(&target, "target data").expect("write target");
        std::os::unix::fs::symlink(&target, &link).expect("create symlink");

        assert!(matches!(
            read_recovery_snapshot(&link),
            Err(DocumentIoError::InvalidTarget)
        ));
        assert!(matches!(
            write_recovery_snapshot_atomically(&link, "replacement"),
            Err(DocumentIoError::InvalidTarget)
        ));
        assert!(matches!(
            remove_recovery_snapshot(&link),
            Err(DocumentIoError::InvalidTarget)
        ));
        assert_eq!(fs::read_to_string(target).unwrap(), "target data");
    }

    #[test]
    fn stale_recovery_writes_cannot_replace_a_newer_snapshot() {
        let directory = tempfile::tempdir().expect("temporary directory");
        let path = directory.path().join("recovery.json");
        let sequence = RecoverySnapshotSequence::default();

        assert!(sequence.write_if_newer(&path, 2, Some("newer")).unwrap());
        assert!(!sequence.write_if_newer(&path, 1, Some("older")).unwrap());
        assert_eq!(fs::read_to_string(&path).unwrap(), "newer");
        assert!(sequence.write_if_newer(&path, 3, None).unwrap());
        assert!(!sequence
            .write_if_newer(&path, 2, Some("stale restore"))
            .unwrap());
        assert_eq!(read_recovery_snapshot(&path).unwrap(), None);
    }

    #[test]
    fn path_validation_requires_absolute_jps_file() {
        let absolute = std::env::current_dir()
            .expect("current directory")
            .join("score.JPS");
        assert!(validate_jps_path(&absolute).is_ok());
        assert!(matches!(
            validate_jps_path(Path::new("score.jps")),
            Err(DocumentIoError::InvalidPath)
        ));
        assert!(matches!(
            validate_jps_path(&absolute.with_extension("txt")),
            Err(DocumentIoError::UnsupportedExtension)
        ));
    }

    #[test]
    fn selected_file_grants_are_exact_and_bounded() {
        let directory = tempfile::tempdir().expect("temporary directory");
        let selected = SelectedJpsFiles::default();
        let paths: Vec<_> = (0..=MAX_SELECTED_JPS_FILES)
            .map(|index| directory.path().join(format!("score-{index}.jps")))
            .collect();

        for path in &paths {
            selected.remember(path.clone()).expect("remember selection");
        }

        assert!(!selected.allows(&paths[0]).expect("check selection"));
        assert!(selected
            .allows(paths.last().expect("last selection"))
            .expect("check selection"));
        assert!(!selected
            .allows(&directory.path().join("other.jps"))
            .expect("check unrelated path"));
    }

    #[test]
    fn read_rejects_oversized_and_invalid_utf8() {
        let directory = tempfile::tempdir().expect("temporary directory");
        let oversized = directory.path().join("oversized.jps");
        fs::write(&oversized, vec![b'0'; MAX_JPS_FILE_BYTES + 1]).expect("write source");
        assert!(matches!(
            read_jps_text(&oversized),
            Err(DocumentIoError::TooLarge)
        ));

        let invalid = directory.path().join("invalid.jps");
        fs::write(&invalid, [0xff, 0xfe]).expect("write source");
        assert!(matches!(
            read_jps_text(&invalid),
            Err(DocumentIoError::InvalidUtf8)
        ));
    }

    #[test]
    fn read_rejects_non_files() {
        let directory = tempfile::tempdir().expect("temporary directory");
        let path = directory.path().join("not-a-file.jps");
        fs::create_dir(&path).expect("create directory");

        assert!(matches!(
            read_jps_text(&path),
            Err(DocumentIoError::InvalidTarget)
        ));
    }

    #[test]
    fn examples_are_regular_jps_files_sorted_without_case_sensitivity() {
        let directory = tempfile::tempdir().expect("temporary directory");
        fs::write(directory.path().join("zeta.JPS"), "Q: 1 |").expect("write example");
        fs::write(directory.path().join("Alpha.jps"), "Q: 2 |").expect("write example");
        fs::write(directory.path().join("notes.txt"), "not JPS").expect("write other file");
        fs::create_dir(directory.path().join("folder.jps")).expect("create directory");

        assert_eq!(
            list_jps_examples(directory.path()).expect("list examples"),
            ["Alpha.jps", "zeta.JPS"]
        );
        assert_eq!(
            read_jps_example(directory.path(), "Alpha.jps").expect("read example"),
            "Q: 2 |"
        );
    }

    #[test]
    fn example_names_cannot_escape_the_catalog() {
        let directory = tempfile::tempdir().expect("temporary directory");
        assert!(matches!(
            read_jps_example(directory.path(), "../outside.jps"),
            Err(DocumentIoError::InvalidPath)
        ));
        assert!(matches!(
            read_jps_example(directory.path(), "nested\\outside.jps"),
            Err(DocumentIoError::InvalidPath)
        ));
    }

    #[test]
    fn importing_creates_distinct_working_copies_without_modifying_source() {
        let directory = tempfile::tempdir().expect("temporary directory");
        let source = directory.path().join("original");
        let copies = directory.path().join("app-data/working-copies");
        fs::create_dir(&source).expect("create source directory");
        let original = source.join("Score.jps");
        fs::write(&original, "original source").expect("write original");

        let first = create_jps_working_copy(&copies, "Score.jps", "first imported copy")
            .expect("create first copy");
        let second = create_jps_working_copy(&copies, "Score.jps", "second imported copy")
            .expect("create second copy");

        assert_eq!(first.file_name().unwrap(), "Score.jps");
        assert_eq!(second.file_name().unwrap(), "Score (2).jps");
        assert_eq!(fs::read_to_string(&original).unwrap(), "original source");
        assert_eq!(fs::read_to_string(first).unwrap(), "first imported copy");
        assert_eq!(fs::read_to_string(second).unwrap(), "second imported copy");
    }

    #[test]
    fn working_copy_rejects_path_names_and_oversized_source() {
        let directory = tempfile::tempdir().expect("temporary directory");
        assert!(matches!(
            create_jps_working_copy(directory.path(), "../score.jps", "Q: 1 |"),
            Err(DocumentIoError::InvalidPath)
        ));
        assert!(matches!(
            create_jps_working_copy(
                directory.path(),
                "score.jps",
                &"0".repeat(MAX_JPS_FILE_BYTES + 1)
            ),
            Err(DocumentIoError::TooLarge)
        ));
    }

    #[test]
    fn atomic_write_replaces_complete_document() {
        let directory = tempfile::tempdir().expect("temporary directory");
        let path = directory.path().join("score.jps");
        fs::write(&path, "old source").expect("write initial source");

        write_jps_text_atomically(&path, "新 source").expect("replace source");

        assert_eq!(fs::read_to_string(path).expect("read result"), "新 source");
        assert_eq!(
            fs::read_dir(directory.path())
                .expect("list directory")
                .count(),
            1
        );
    }

    #[test]
    fn atomic_write_refuses_an_externally_changed_document() {
        let directory = tempfile::tempdir().expect("temporary directory");
        let path = directory.path().join("score.jps");
        fs::write(&path, "external edit").expect("write external edit");

        assert!(matches!(
            write_jps_text_atomically_if_unchanged(&path, "previous source", "app source"),
            Err(DocumentIoError::ChangedOnDisk)
        ));
        assert_eq!(
            fs::read_to_string(path).expect("read retained external edit"),
            "external edit"
        );
        assert_eq!(
            fs::read_dir(directory.path())
                .expect("list directory")
                .count(),
            1
        );
    }

    #[test]
    fn atomic_write_accepts_an_unchanged_disk_snapshot() {
        let directory = tempfile::tempdir().expect("temporary directory");
        let path = directory.path().join("score.jps");
        fs::write(&path, "Q: 1 |").expect("write original");

        write_jps_text_atomically_if_unchanged(&path, "Q: 1 |", "Q: 2 |")
            .expect("replace unchanged source");

        assert_eq!(fs::read_to_string(path).expect("read result"), "Q: 2 |");
    }

    #[cfg(unix)]
    #[test]
    fn atomic_write_preserves_existing_permissions() {
        use std::os::unix::fs::PermissionsExt;

        let directory = tempfile::tempdir().expect("temporary directory");
        let path = directory.path().join("score.jps");
        fs::write(&path, "old source").expect("write initial source");
        fs::set_permissions(&path, fs::Permissions::from_mode(0o640)).expect("set permissions");

        write_jps_text_atomically(&path, "new source").expect("replace source");

        assert_eq!(
            fs::metadata(path)
                .expect("read metadata")
                .permissions()
                .mode()
                & 0o777,
            0o640
        );
    }

    #[cfg(unix)]
    #[test]
    fn atomic_write_refuses_symlinks() {
        use std::os::unix::fs::symlink;

        let directory = tempfile::tempdir().expect("temporary directory");
        let target = directory.path().join("target.jps");
        let alias = directory.path().join("alias.jps");
        fs::write(&target, "original").expect("write original");
        symlink(&target, &alias).expect("create symlink");

        assert!(matches!(
            write_jps_text_atomically(&alias, "replacement"),
            Err(DocumentIoError::InvalidTarget)
        ));
        assert_eq!(
            fs::read_to_string(target).expect("read original"),
            "original"
        );
        assert!(alias.is_symlink());
    }

    #[test]
    fn failed_atomic_write_preserves_target_and_cleans_temporary_file() {
        let directory = tempfile::tempdir().expect("temporary directory");
        let target = directory.path().join("target.jps");
        fs::create_dir(&target).expect("create directory target");

        assert!(write_jps_text_atomically(&target, "new source").is_err());

        assert!(target.is_dir());
        assert_eq!(
            fs::read_dir(directory.path())
                .expect("list directory")
                .count(),
            1
        );
    }

    #[test]
    fn oversized_write_does_not_change_existing_file() {
        let directory = tempfile::tempdir().expect("temporary directory");
        let path = directory.path().join("score.jps");
        fs::write(&path, "original").expect("write initial source");

        assert!(matches!(
            write_jps_text_atomically(&path, &"x".repeat(MAX_JPS_FILE_BYTES + 1)),
            Err(DocumentIoError::TooLarge)
        ));
        assert_eq!(fs::read_to_string(path).expect("read source"), "original");
    }
}
