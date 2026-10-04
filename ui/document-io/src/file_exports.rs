use std::fs;
use std::io::{self, Write};
use std::path::{Path, PathBuf};

use same_file::Handle;
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

pub fn publish_export_pages(
    selected_path: &Path,
    format: ExportFormat,
    pages: &[&[u8]],
    replace_existing: bool,
) -> Result<Vec<PathBuf>, DocumentIoError> {
    publish_pages(
        selected_path,
        format,
        pages,
        replace_existing,
        |temporary| Handle::from_file(temporary.as_file().try_clone()?),
    )
}

fn publish_pages(
    selected_path: &Path,
    format: ExportFormat,
    pages: &[&[u8]],
    replace_existing: bool,
    mut identify: impl FnMut(&NamedTempFile) -> io::Result<Handle>,
) -> Result<Vec<PathBuf>, DocumentIoError> {
    if pages.is_empty() || pages.iter().any(|page| page.is_empty()) {
        return Err(DocumentIoError::EmptyExport);
    }
    if pages.len() > MAX_EXPORT_FILES {
        return Err(DocumentIoError::TooManyExportFiles);
    }
    let total_bytes = pages
        .iter()
        .try_fold(0_usize, |total, page| total.checked_add(page.len()));
    if !total_bytes.is_some_and(|bytes| bytes <= MAX_EXPORT_BYTES) {
        return Err(DocumentIoError::ExportTooLarge);
    }

    let targets = page_targets(selected_path, pages.len(), format)?;
    let directory = selected_path
        .parent()
        .filter(|path| !path.as_os_str().is_empty())
        .ok_or(DocumentIoError::InvalidExportPath)?;
    if !directory.is_dir() {
        return Err(DocumentIoError::InvalidTarget);
    }
    let mut existing_targets = Vec::new();
    for target in &targets {
        match fs::symlink_metadata(target) {
            Ok(metadata) if replace_existing && metadata.file_type().is_file() => {
                existing_targets.push(target.clone());
            }
            Ok(_) if replace_existing => return Err(DocumentIoError::InvalidTarget),
            Ok(_) => return Err(DocumentIoError::ExportDestinationExists),
            Err(error) if error.kind() == io::ErrorKind::NotFound => {}
            Err(error) => return Err(DocumentIoError::Io(error)),
        }
    }
    if pages.len() > 1 && !replace_existing {
        match fs::symlink_metadata(selected_path) {
            Ok(_) => return Err(DocumentIoError::ExportDestinationExists),
            Err(error) if error.kind() == io::ErrorKind::NotFound => {}
            Err(error) => return Err(DocumentIoError::Io(error)),
        }
    }

    let mut staged = Vec::with_capacity(pages.len());
    for (target, page) in targets.iter().zip(pages) {
        let mut temporary = NamedTempFile::new_in(directory)?;
        temporary.write_all(page)?;
        temporary.as_file().sync_all()?;
        // Finish every fallible identity lookup before replacing any original.
        let identity = identify(&temporary)?;
        staged.push((target.clone(), temporary, identity));
    }

    let backup_directory = if existing_targets.is_empty() {
        None
    } else {
        Some(tempfile::TempDir::new_in(directory)?)
    };
    let mut backups = Vec::with_capacity(existing_targets.len());
    if let Some(backup_directory) = &backup_directory {
        for (index, target) in existing_targets.iter().enumerate() {
            let backup = backup_directory.path().join(format!("target-{index}"));
            match fs::copy(target, &backup) {
                Ok(_) => {
                    backups.push((target.clone(), backup));
                }
                Err(error) if error.kind() == io::ErrorKind::NotFound => {}
                Err(error) => return Err(DocumentIoError::Io(error)),
            }
        }
    }

    let mut published = Vec::with_capacity(targets.len());
    for (target, temporary, identity) in staged {
        let backup = backups
            .iter()
            .find(|(original, _)| original == &target)
            .map(|(_, backup)| backup.clone());
        let result = if backup.is_some() {
            temporary.persist(&target)
        } else {
            temporary.persist_noclobber(&target)
        };
        match result {
            Ok(_) => published.push((target, identity, backup)),
            Err(error) => {
                let already_exists = error.error.kind() == io::ErrorKind::AlreadyExists;
                drop(error.file);
                if !rollback_published(&published) {
                    return Err(DocumentIoError::PartialExport {
                        recovery_location: preserve_recovery_files(backup_directory, directory),
                    });
                }
                return Err(if already_exists {
                    DocumentIoError::ExportDestinationExists
                } else {
                    DocumentIoError::Io(error.error)
                });
            }
        }
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
                    if fs::rename(backup, path).is_err() {
                        complete = false;
                    }
                }
            }
            Ok(_) => complete = false,
            Err(error) if error.kind() == io::ErrorKind::NotFound => {
                if let Some(backup) = backup {
                    if fs::rename(backup, path).is_err() {
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
        preserve_recovery_files, publish_export_pages, publish_pages, rollback_published,
        ExportFormat, MAX_EXPORT_BYTES,
    };
    use crate::DocumentIoError;

    fn publish_svg_pages(
        selected_path: &Path,
        pages: &[String],
    ) -> Result<Vec<PathBuf>, DocumentIoError> {
        let pages = pages.iter().map(String::as_bytes).collect::<Vec<_>>();
        publish_export_pages(selected_path, ExportFormat::Svg, &pages, false)
    }

    fn replace_svg_pages(
        selected_path: &Path,
        pages: &[String],
    ) -> Result<Vec<PathBuf>, DocumentIoError> {
        let pages = pages.iter().map(String::as_bytes).collect::<Vec<_>>();
        publish_export_pages(selected_path, ExportFormat::Svg, &pages, true)
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
            &[b"first replacement", b"second replacement"],
            true,
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

        let outputs = publish_export_pages(&selected, ExportFormat::Jpg, &pages, false).unwrap();

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
    fn multi_page_dialog_base_path_must_also_be_unused() {
        let directory = tempdir().expect("temporary directory");
        let selected = directory.path().join("Song.svg");
        fs::write(&selected, "keep selected target").expect("write selected target");

        assert!(matches!(
            publish_svg_pages(&selected, &["page one".into(), "page two".into()]),
            Err(DocumentIoError::ExportDestinationExists)
        ));
        assert_eq!(
            fs::read_to_string(&selected).unwrap(),
            "keep selected target"
        );
        assert!(!directory.path().join("Song_page_001.svg").exists());
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
                false
            ),
            Err(DocumentIoError::InvalidExportPath)
        ));
    }
}
