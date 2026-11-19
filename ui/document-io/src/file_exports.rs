use std::fs::{self, File};
use std::io::{self, Write};
use std::path::{Path, PathBuf};

use same_file::Handle;
use sha2::{Digest, Sha256};
use tempfile::NamedTempFile;

use crate::DocumentIoError;

pub const MAX_EXPORT_BYTES: usize = 64 * 1024 * 1024;
pub const MAX_EXPORT_FILES: usize = 200;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ExportFormat {
    Svg,
    Pdf,
    Jpg,
    Png,
}

impl ExportFormat {
    fn extension(self) -> &'static str {
        match self {
            Self::Svg => "svg",
            Self::Pdf => "pdf",
            Self::Jpg => "jpg",
            Self::Png => "png",
        }
    }
}

#[derive(Debug)]
pub struct ConfirmedExportTarget {
    path: PathBuf,
    version: ExportTargetVersion,
}

impl ConfirmedExportTarget {
    pub fn path(&self) -> &Path {
        &self.path
    }
}

#[derive(Debug, PartialEq, Eq)]
struct ExportTargetVersion {
    identity: Handle,
    digest: [u8; 32],
}

impl ExportTargetVersion {
    fn read(path: &Path) -> Result<Self, DocumentIoError> {
        if !fs::symlink_metadata(path)?.is_file() {
            return Err(DocumentIoError::InvalidTarget);
        }
        let mut file = File::open(path)?;
        if !file.metadata()?.is_file() {
            return Err(DocumentIoError::InvalidTarget);
        }
        let identity = Handle::from_file(file.try_clone()?)?;
        let mut digest = Sha256::new();
        io::copy(&mut file, &mut digest)?;
        Ok(Self {
            identity,
            digest: digest.finalize().into(),
        })
    }
}

pub fn publish_export_pages(
    selected_path: &Path,
    format: ExportFormat,
    pages: &[&[u8]],
    confirmed_existing: &[ConfirmedExportTarget],
) -> Result<Vec<PathBuf>, DocumentIoError> {
    publish_generated_pages(
        selected_path,
        format,
        pages.len(),
        confirmed_existing,
        |index| Ok(pages[index]),
    )
}

pub(crate) fn publish_generated_pages<T: AsRef<[u8]>>(
    selected_path: &Path,
    format: ExportFormat,
    page_count: usize,
    confirmed_existing: &[ConfirmedExportTarget],
    generate: impl FnMut(usize) -> Result<T, DocumentIoError>,
) -> Result<Vec<PathBuf>, DocumentIoError> {
    publish_pages(
        selected_path,
        format,
        page_count,
        confirmed_existing,
        generate,
        |temporary| Handle::from_file(temporary.as_file().try_clone()?),
    )
}

fn publish_pages<T: AsRef<[u8]>>(
    selected_path: &Path,
    format: ExportFormat,
    page_count: usize,
    confirmed_existing: &[ConfirmedExportTarget],
    mut generate: impl FnMut(usize) -> Result<T, DocumentIoError>,
    mut identify: impl FnMut(&NamedTempFile) -> io::Result<Handle>,
) -> Result<Vec<PathBuf>, DocumentIoError> {
    if page_count == 0 {
        return Err(DocumentIoError::EmptyExport);
    }
    if page_count > MAX_EXPORT_FILES {
        return Err(DocumentIoError::TooManyExportFiles);
    }
    let targets = page_targets(selected_path, page_count, format)?;
    let directory = selected_path
        .parent()
        .filter(|path| !path.as_os_str().is_empty())
        .ok_or(DocumentIoError::InvalidExportPath)?;
    if !directory.is_dir() {
        return Err(DocumentIoError::InvalidTarget);
    }
    for target in &targets {
        let confirmed = confirmed_existing.iter().any(|file| file.path == *target);
        match fs::symlink_metadata(target) {
            Ok(metadata) if confirmed && metadata.file_type().is_file() => {}
            Ok(_) if confirmed => return Err(DocumentIoError::ExportTargetChanged(target.clone())),
            Ok(_) => return Err(DocumentIoError::ExportDestinationExists),
            Err(error) if error.kind() == io::ErrorKind::NotFound => {
                if confirmed {
                    return Err(DocumentIoError::ExportTargetChanged(target.clone()));
                }
            }
            Err(error) => return Err(DocumentIoError::Io(error)),
        }
    }
    let mut staged = Vec::with_capacity(page_count);
    let mut total_bytes = 0_usize;
    for (index, target) in targets.iter().enumerate() {
        let page = generate(index)?;
        let bytes = page.as_ref();
        if bytes.is_empty() {
            return Err(DocumentIoError::EmptyExport);
        }
        total_bytes = total_bytes
            .checked_add(bytes.len())
            .filter(|total| *total <= MAX_EXPORT_BYTES)
            .ok_or(DocumentIoError::ExportTooLarge)?;
        let mut temporary = NamedTempFile::new_in(directory)?;
        temporary.write_all(bytes)?;
        temporary.as_file().sync_all()?;
        // Finish every fallible identity lookup before replacing any original.
        let identity = identify(&temporary)?;
        staged.push((target.clone(), temporary, identity));
    }

    let backup_directory = if confirmed_existing.is_empty() {
        None
    } else {
        Some(
            tempfile::Builder::new()
                .prefix("octopus-export-")
                .tempdir_in(directory)?,
        )
    };
    let mut published = Vec::with_capacity(targets.len());
    for (target, temporary, identity) in staged {
        let mut backup = None;
        let result = (|| {
            if let Some(confirmation) = confirmed_existing.iter().find(|file| file.path == target) {
                let filename = target
                    .file_name()
                    .ok_or(DocumentIoError::InvalidExportPath)?;
                let original = backup_directory
                    .as_ref()
                    .expect("confirmed targets have a backup directory")
                    .path()
                    .join(filename);
                // Move the original aside before checking it. Publishing into the vacant path
                // with no-clobber then cannot overwrite a file created after this check.
                fs::rename(&target, &original).map_err(|error| {
                    if error.kind() == io::ErrorKind::NotFound {
                        DocumentIoError::ExportTargetChanged(target.clone())
                    } else {
                        DocumentIoError::Io(error)
                    }
                })?;
                let version = ExportTargetVersion::read(&original);
                backup = Some(original);
                if !version.is_ok_and(|version| version == confirmation.version) {
                    return Err(DocumentIoError::ExportTargetChanged(target.clone()));
                }
            }
            temporary.persist_noclobber(&target).map_err(|error| {
                if error.error.kind() == io::ErrorKind::AlreadyExists {
                    DocumentIoError::ExportDestinationExists
                } else {
                    DocumentIoError::Io(error.error)
                }
            })?;
            Ok(())
        })();
        if let Err(error) = result {
            let current_restored = backup
                .as_ref()
                .is_none_or(|path| restore_backup(path, &target));
            let prior_restored = rollback_published(&published);
            if !current_restored || !prior_restored {
                return Err(DocumentIoError::PartialExport {
                    recovery_location: preserve_recovery_files(backup_directory, directory),
                });
            }
            return Err(error);
        }
        published.push((target, identity, backup));
    }
    Ok(targets)
}

fn preserve_recovery_files(
    backup_directory: Option<tempfile::TempDir>,
    destination_directory: &Path,
) -> PathBuf {
    backup_directory.map_or_else(
        || destination_directory.to_path_buf(),
        tempfile::TempDir::keep,
    )
}

pub fn existing_export_targets(
    selected_path: &Path,
    format: ExportFormat,
    page_count: usize,
) -> Result<Vec<ConfirmedExportTarget>, DocumentIoError> {
    if page_count == 0 {
        return Err(DocumentIoError::EmptyExport);
    }
    if page_count > MAX_EXPORT_FILES {
        return Err(DocumentIoError::TooManyExportFiles);
    }
    let mut existing = Vec::new();
    for target in page_targets(selected_path, page_count, format)? {
        match ExportTargetVersion::read(&target) {
            Ok(version) => existing.push(ConfirmedExportTarget {
                path: target,
                version,
            }),
            Err(DocumentIoError::Io(error)) if error.kind() == io::ErrorKind::NotFound => {}
            Err(error) => return Err(error),
        }
    }
    Ok(existing)
}

fn page_targets(
    selected_path: &Path,
    page_count: usize,
    format: ExportFormat,
) -> Result<Vec<PathBuf>, DocumentIoError> {
    if !selected_path.is_absolute()
        || selected_path
            .components()
            .any(|component| component == std::path::Component::ParentDir)
        || !selected_path
            .extension()
            .and_then(|extension| extension.to_str())
            .is_some_and(|extension| extension.eq_ignore_ascii_case(format.extension()))
    {
        return Err(DocumentIoError::InvalidExportPath);
    }
    if page_count == 1 {
        return Ok(vec![selected_path.to_path_buf()]);
    }

    let stem = selected_path
        .file_stem()
        .and_then(|stem| stem.to_str())
        .filter(|stem| !stem.is_empty())
        .ok_or(DocumentIoError::InvalidExportPath)?;
    let directory = selected_path
        .parent()
        .ok_or(DocumentIoError::InvalidExportPath)?;
    Ok((1..=page_count)
        .map(|page_number| {
            directory.join(format!(
                "{stem}_page_{page_number:03}.{}",
                format.extension()
            ))
        })
        .collect())
}

fn restore_backup(backup: &Path, target: &Path) -> bool {
    let Ok(mut backup) = tempfile::TempPath::try_from_path(backup) else {
        return false;
    };
    backup.disable_cleanup(true);
    backup.persist_noclobber(target).is_ok()
}

fn rollback_published(paths: &[(PathBuf, Handle, Option<PathBuf>)]) -> bool {
    let mut complete = true;
    for (path, identity, backup) in paths.iter().rev() {
        match Handle::from_path(path) {
            Ok(current) if current == *identity => {
                if let Err(error) = fs::remove_file(path) {
                    if error.kind() != io::ErrorKind::NotFound {
                        complete = false;
                        continue;
                    }
                }
                if let Some(backup) = backup {
                    if !restore_backup(backup, path) {
                        complete = false;
                    }
                }
            }
            Ok(_) => complete = false,
            Err(error) if error.kind() == io::ErrorKind::NotFound => {
                if let Some(backup) = backup {
                    if !restore_backup(backup, path) {
                        complete = false;
                    }
                }
            }
            Err(_) => complete = false,
        }
    }
    complete
}

#[cfg(test)]
mod tests {
    use std::fs;
    use std::io::{self, Write};
    use std::path::{Path, PathBuf};

    use same_file::Handle;
    use tempfile::{tempdir, NamedTempFile};

    use super::{
        existing_export_targets, preserve_recovery_files, publish_export_pages, publish_pages,
        rollback_published, ExportFormat, MAX_EXPORT_BYTES,
    };
    use crate::DocumentIoError;

    fn publish_svg_pages(
        selected_path: &Path,
        pages: &[String],
    ) -> Result<Vec<PathBuf>, DocumentIoError> {
        let pages = pages.iter().map(String::as_bytes).collect::<Vec<_>>();
        publish_export_pages(selected_path, ExportFormat::Svg, &pages, &[])
    }

    fn replace_svg_pages(
        selected_path: &Path,
        pages: &[String],
    ) -> Result<Vec<PathBuf>, DocumentIoError> {
        let pages = pages.iter().map(String::as_bytes).collect::<Vec<_>>();
        publish_export_pages(
            selected_path,
            ExportFormat::Svg,
            &pages,
            &existing_export_targets(selected_path, ExportFormat::Svg, pages.len())?,
        )
    }

    #[test]
    fn later_identity_failure_leaves_every_original_untouched() {
        let directory = tempdir().unwrap();
        let selected = directory.path().join("Song.svg");
        let first = directory.path().join("Song_page_001.svg");
        let second = directory.path().join("Song_page_002.svg");
        fs::write(&first, "first original").unwrap();
        fs::write(&second, "second original").unwrap();
        let mut calls = 0;
        let result = publish_pages(
            &selected,
            ExportFormat::Svg,
            2,
            &existing_export_targets(&selected, ExportFormat::Svg, 2).unwrap(),
            |index| {
                Ok([
                    b"first replacement".as_slice(),
                    b"second replacement".as_slice(),
                ][index])
            },
            |temporary| {
                calls += 1;
                if calls == 2 {
                    return Err(io::Error::other("injected identity lookup failure"));
                }
                Handle::from_file(temporary.as_file().try_clone()?)
            },
        );

        assert!(result.is_err());
        assert_eq!(fs::read_to_string(first).unwrap(), "first original");
        assert_eq!(fs::read_to_string(second).unwrap(), "second original");
        assert_eq!(fs::read_dir(directory.path()).unwrap().count(), 2);
    }

    #[test]
    fn changed_confirmed_file_aborts_and_restores_earlier_pages() {
        let directory = tempdir().unwrap();
        let selected = directory.path().join("Song.svg");
        let first = directory.path().join("Song_page_001.svg");
        let second = directory.path().join("Song_page_002.svg");
        fs::write(&first, b"first original").unwrap();
        fs::write(&second, b"second original").unwrap();
        let confirmed = existing_export_targets(&selected, ExportFormat::Svg, 2).unwrap();
        let result =
            super::publish_generated_pages(&selected, ExportFormat::Svg, 2, &confirmed, |index| {
                if index == 1 {
                    // Modify in place without changing identity or length.
                    fs::write(&second, b"second modified")?;
                }
                Ok(b"export")
            });
        assert!(
            matches!(result, Err(DocumentIoError::ExportTargetChanged(path)) if path == second)
        );
        assert_eq!(fs::read(&first).unwrap(), b"first original");
        assert_eq!(fs::read(&second).unwrap(), b"second modified");
        assert_eq!(fs::read_dir(directory.path()).unwrap().count(), 2);
    }

    #[test]
    fn replacement_with_identical_bytes_requires_new_confirmation() {
        let directory = tempdir().unwrap();
        let target = directory.path().join("Song.svg");
        fs::write(&target, b"original bytes").unwrap();
        let confirmed = existing_export_targets(&target, ExportFormat::Svg, 1).unwrap();
        let replacement = NamedTempFile::new_in(directory.path()).unwrap();
        fs::write(replacement.path(), b"original bytes").unwrap();
        replacement.persist(&target).unwrap();
        assert!(
            matches!(publish_export_pages(&target, ExportFormat::Svg, &[b"export"], &confirmed),
                         Err(DocumentIoError::ExportTargetChanged(path)) if path == target)
        );
        assert_eq!(fs::read(&target).unwrap(), b"original bytes");
    }

    #[test]
    fn restore_leaves_a_new_occupant_and_retains_the_original() {
        let directory = tempdir().unwrap();
        let target = directory.path().join("Song.svg");
        let backup = directory.path().join("original.svg");
        fs::write(&target, b"new occupant").unwrap();
        fs::write(&backup, b"original bytes").unwrap();
        assert!(!super::restore_backup(&backup, &target));
        assert_eq!(fs::read(&target).unwrap(), b"new occupant");
        assert_eq!(fs::read(&backup).unwrap(), b"original bytes");
    }

    #[test]
    fn publishes_a_single_page_at_the_selected_path() {
        let directory = tempdir().expect("temporary directory");
        let target = directory.path().join("曲.svg");
        let pages = vec!["<svg>score</svg>".to_owned()];

        assert_eq!(
            publish_svg_pages(&target, &pages).unwrap(),
            std::slice::from_ref(&target)
        );
        assert_eq!(fs::read_to_string(target).unwrap(), pages[0]);
    }

    #[test]
    fn repeated_multi_page_exports_confirm_the_numbered_output_paths() {
        let directory = tempdir().unwrap();
        for (format, extension) in [
            (ExportFormat::Svg, "svg"),
            (ExportFormat::Png, "png"),
            (ExportFormat::Jpg, "jpg"),
        ] {
            let selected = directory.path().join(format!("Song.{extension}"));
            let outputs =
                publish_export_pages(&selected, format, &[b"first", b"second"], &[]).unwrap();
            assert!(!selected.exists());
            let confirmed = existing_export_targets(&selected, format, 2).unwrap();
            assert_eq!(
                confirmed.iter().map(|file| file.path()).collect::<Vec<_>>(),
                outputs
            );
            publish_export_pages(
                &selected,
                format,
                &[b"updated first", b"updated second"],
                &confirmed,
            )
            .unwrap();
            assert_eq!(fs::read(&outputs[0]).unwrap(), b"updated first");
            assert_eq!(fs::read(&outputs[1]).unwrap(), b"updated second");
        }
    }

    #[test]
    fn a_later_collision_is_not_covered_by_another_files_confirmation() {
        let directory = tempdir().unwrap();
        let selected = directory.path().join("Song.svg");
        let first = directory.path().join("Song_page_001.svg");
        let second = directory.path().join("Song_page_002.svg");
        fs::write(&first, "confirmed original").unwrap();
        let confirmed = existing_export_targets(&selected, ExportFormat::Svg, 2).unwrap();
        assert_eq!(confirmed.len(), 1);
        assert_eq!(confirmed[0].path(), first);
        fs::write(&second, "unconfirmed original").unwrap();
        assert!(matches!(
            publish_export_pages(
                &selected,
                ExportFormat::Svg,
                &[b"new first", b"new second"],
                &confirmed
            ),
            Err(DocumentIoError::ExportDestinationExists)
        ));
        assert_eq!(fs::read_to_string(&first).unwrap(), "confirmed original");
        assert_eq!(fs::read_to_string(&second).unwrap(), "unconfirmed original");
    }

    #[test]
    fn names_multi_page_exports_with_a_one_based_padded_suffix() {
        let directory = tempdir().expect("temporary directory");
        let selected = directory.path().join("Song.svg");
        let pages = vec!["page one".to_owned(), "page two".to_owned()];

        let outputs = publish_svg_pages(&selected, &pages).unwrap();

        assert_eq!(outputs[0].file_name().unwrap(), "Song_page_001.svg");
        assert_eq!(outputs[1].file_name().unwrap(), "Song_page_002.svg");
        assert_eq!(fs::read_to_string(&outputs[0]).unwrap(), pages[0]);
        assert_eq!(fs::read_to_string(&outputs[1]).unwrap(), pages[1]);
    }

    #[test]
    fn uses_jpg_extension_for_multi_page_outputs() {
        let directory = tempdir().expect("temporary directory");
        let selected = directory.path().join("曲.jpg");
        let pages = [b"first".as_slice(), b"second".as_slice()];

        let outputs = publish_export_pages(&selected, ExportFormat::Jpg, &pages, &[]).unwrap();

        assert_eq!(outputs[0].file_name().unwrap(), "曲_page_001.jpg");
        assert_eq!(outputs[1].file_name().unwrap(), "曲_page_002.jpg");
    }

    #[test]
    fn collision_rejects_the_complete_batch_without_changing_existing_files() {
        let directory = tempdir().expect("temporary directory");
        let selected = directory.path().join("Song.svg");
        let collision = directory.path().join("Song_page_002.svg");
        fs::write(&collision, "keep existing").expect("write collision target");
        let pages = vec!["page one".to_owned(), "page two".to_owned()];

        assert!(matches!(
            publish_svg_pages(&selected, &pages),
            Err(DocumentIoError::ExportDestinationExists)
        ));
        assert!(!directory.path().join("Song_page_001.svg").exists());
        assert_eq!(fs::read_to_string(collision).unwrap(), "keep existing");
    }

    #[test]
    fn confirmed_replacement_replaces_existing_export_files() {
        let directory = tempdir().expect("temporary directory");
        let selected = directory.path().join("Song.svg");
        let first = directory.path().join("Song_page_001.svg");
        let second = directory.path().join("Song_page_002.svg");
        fs::write(&selected, "keep selected path").expect("write selected path");
        fs::write(&first, "old page one").expect("write first page");
        fs::write(&second, "old page two").expect("write second page");

        let outputs =
            replace_svg_pages(&selected, &["new page one".into(), "new page two".into()]).unwrap();

        assert_eq!(fs::read_to_string(&first).unwrap(), "new page one");
        assert_eq!(fs::read_to_string(&second).unwrap(), "new page two");
        assert_eq!(fs::read_to_string(&selected).unwrap(), "keep selected path");
        assert_eq!(outputs, vec![first, second]);
    }

    #[test]
    fn confirmed_replacement_overwrites_a_single_page() {
        let directory = tempdir().expect("temporary directory");
        let target = directory.path().join("Song.svg");
        fs::write(&target, "old page").expect("write existing export");

        replace_svg_pages(&target, &["new page".into()]).unwrap();

        assert_eq!(fs::read_to_string(target).unwrap(), "new page");
    }

    #[test]
    fn multi_page_export_preserves_an_unused_dialog_base_path() {
        let directory = tempdir().expect("temporary directory");
        let selected = directory.path().join("Song.svg");
        fs::write(&selected, "keep selected target").expect("write selected target");

        publish_svg_pages(&selected, &["page one".into(), "page two".into()]).unwrap();
        assert_eq!(
            fs::read_to_string(&selected).unwrap(),
            "keep selected target"
        );
        assert_eq!(
            fs::read_to_string(directory.path().join("Song_page_001.svg")).unwrap(),
            "page one"
        );
    }

    #[test]
    fn rollback_removes_only_the_published_file_identity() {
        let directory = tempdir().expect("temporary directory");
        let owned = directory.path().join("published.svg");
        let replaced = directory.path().join("replaced.svg");
        fs::write(&owned, "ours").expect("write published file");
        fs::write(&replaced, "ours before replacement").expect("write replaced file");
        let owned_identity = Handle::from_path(&owned).unwrap();
        let replaced_identity = Handle::from_path(&replaced).unwrap();
        let published = vec![
            (owned.clone(), owned_identity, None),
            (replaced.clone(), replaced_identity, None),
        ];
        fs::remove_file(&replaced).expect("remove old published path");
        fs::write(&replaced, "external file").expect("write external replacement");

        assert!(!rollback_published(&published));
        assert!(!owned.exists());
        assert_eq!(fs::read_to_string(replaced).unwrap(), "external file");
    }

    #[test]
    fn rollback_restores_a_replaced_file_from_its_backup() {
        let directory = tempdir().expect("temporary directory");
        let target = directory.path().join("published.svg");
        let backup = directory.path().join("original.svg");
        fs::write(&target, "old contents").expect("write original file");
        fs::write(&backup, "old contents").expect("write backup file");
        let mut replacement = NamedTempFile::new_in(directory.path()).expect("stage replacement");
        replacement
            .write_all(b"new contents")
            .expect("write replacement");
        let identity = Handle::from_file(
            replacement
                .as_file()
                .try_clone()
                .expect("clone staged replacement"),
        )
        .expect("capture staged file identity");
        replacement.persist(&target).expect("replace original file");
        let published = vec![(target.clone(), identity, Some(backup.clone()))];

        assert!(rollback_published(&published));
        assert_eq!(fs::read_to_string(target).unwrap(), "old contents");
        assert!(!backup.exists());
    }

    #[test]
    fn incomplete_rollback_reports_the_preserved_backup_location() {
        let directory = tempdir().expect("temporary directory");
        let backup_directory = tempfile::TempDir::new_in(directory.path()).unwrap();
        let backup = backup_directory.path().join("target-0");
        fs::write(&backup, "original contents").expect("write backup");

        let location = preserve_recovery_files(Some(backup_directory), directory.path());

        assert_eq!(
            fs::read(location.join("target-0")).unwrap(),
            b"original contents"
        );
        let error = DocumentIoError::PartialExport {
            recovery_location: location.clone(),
        };
        assert!(error.to_string().contains(&location.display().to_string()));
    }

    #[test]
    fn rollback_attempts_every_owned_path_after_a_removal_error() {
        let directory = tempdir().expect("temporary directory");
        let file = directory.path().join("published.svg");
        let folder = directory.path().join("not-a-file.svg");
        fs::write(&file, "published").expect("write published file");
        fs::create_dir(&folder).expect("create non-file target");
        let published = vec![
            (file.clone(), Handle::from_path(&file).unwrap(), None),
            (folder.clone(), Handle::from_path(&folder).unwrap(), None),
        ];

        assert!(!rollback_published(&published));
        assert!(!file.exists());
        assert!(folder.is_dir());
    }

    #[test]
    fn rejects_empty_oversized_and_mismatched_exports() {
        let directory = tempdir().expect("temporary directory");
        let target = directory.path().join("Song.svg");

        assert!(matches!(
            publish_svg_pages(&target, &[]),
            Err(DocumentIoError::EmptyExport)
        ));
        assert!(matches!(
            publish_svg_pages(&target, &[String::new()]),
            Err(DocumentIoError::EmptyExport)
        ));
        assert!(matches!(
            publish_svg_pages(&target, &["x".repeat(MAX_EXPORT_BYTES + 1)]),
            Err(DocumentIoError::ExportTooLarge)
        ));
        assert!(matches!(
            publish_svg_pages(&directory.path().join("Song.txt"), &["svg".into()]),
            Err(DocumentIoError::InvalidExportPath)
        ));
        assert!(matches!(
            publish_export_pages(
                &directory.path().join("Song.svg"),
                ExportFormat::Pdf,
                &[b"pdf"],
                &[]
            ),
            Err(DocumentIoError::InvalidExportPath)
        ));
    }
}
