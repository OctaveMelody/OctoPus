use std::fs;
use std::io;
use std::path::{Path, PathBuf};

use tauri::WebviewWindow;
use tauri_plugin_dialog::{DialogExt, MessageDialogButtons};

pub(super) fn normalized_save_path(selected: &Path, extension: &str) -> Result<PathBuf, String> {
    let mut target = selected.to_path_buf();
    if target.extension().is_none() {
        target.set_extension(extension);
    }
    if !target
        .extension()
        .and_then(|value| value.to_str())
        .is_some_and(|value| value.eq_ignore_ascii_case(extension))
    {
        return Err(format!(
            "save destination must use the .{extension} extension"
        ));
    }
    Ok(target)
}

pub(super) fn existing_file(path: &Path) -> Result<bool, String> {
    match fs::symlink_metadata(path) {
        Ok(metadata) if metadata.file_type().is_file() => Ok(true),
        Ok(_) => Err("save target must be a regular file".into()),
        Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(false),
        Err(error) => Err(format!("could not inspect save destination: {error}")),
    }
}

pub(super) fn approved_save_path(
    selected: &Path,
    extension: &str,
    confirm: impl FnOnce(&[PathBuf]) -> bool,
) -> Result<Option<(PathBuf, bool)>, String> {
    let target = normalized_save_path(selected, extension)?;
    let replace_existing = existing_file(&target)?;
    if target != selected && replace_existing && !confirm(std::slice::from_ref(&target)) {
        return Ok(None);
    }
    Ok(Some((target, replace_existing)))
}

pub(super) fn confirm_replacements(window: &WebviewWindow, paths: &[PathBuf]) -> bool {
    if paths.is_empty() {
        return true;
    }
    let mut names = paths
        .iter()
        .take(8)
        .map(|path| path.display().to_string())
        .collect::<Vec<_>>()
        .join("\n");
    if paths.len() > 8 {
        names.push_str(&format!("\n… and {} more files", paths.len() - 8));
    }
    window
        .dialog()
        .message(format!(
            "Replace {} existing file(s)?\n\n{names}",
            paths.len()
        ))
        .parent(window)
        .title("Replace existing files")
        .buttons(MessageDialogButtons::YesNo)
        .blocking_show()
}

#[cfg(test)]
mod tests {
    use super::{approved_save_path, existing_file, normalized_save_path};
    use std::fs;

    #[test]
    fn extensionless_selection_checks_the_actual_destination() {
        let directory =
            std::env::temp_dir().join(format!("octopus-save-dialog-{}", std::process::id()));
        fs::create_dir_all(&directory).unwrap();
        let selected = directory.join("Existing");
        let target = directory.join("Existing.jps");
        fs::write(&target, "original score").unwrap();
        assert!(!existing_file(&selected).unwrap());
        assert_eq!(normalized_save_path(&selected, "jps").unwrap(), target);
        assert!(existing_file(&target).unwrap());
        let cancelled = approved_save_path(&selected, "jps", |paths| {
            assert_eq!(paths, std::slice::from_ref(&target));
            false
        })
        .unwrap();
        assert!(cancelled.is_none());
        assert_eq!(fs::read_to_string(&target).unwrap(), "original score");
        let approved = approved_save_path(&selected, "jps", |_| true).unwrap();
        assert_eq!(approved, Some((target.clone(), true)));
        let unchanged = approved_save_path(&target, "jps", |_| {
            panic!("native dialog already confirmed the literal filename")
        })
        .unwrap();
        assert_eq!(unchanged, Some((target.clone(), true)));
        let new_file = approved_save_path(&directory.join("new"), "jps", |_| {
            panic!("new files need no overwrite confirmation")
        })
        .unwrap();
        assert_eq!(new_file, Some((directory.join("new.jps"), false)));
        assert_eq!(normalized_save_path(&target, "jps").unwrap(), target);
        assert!(normalized_save_path(&directory.join("wrong.txt"), "jps").is_err());
        assert!(existing_file(&directory).is_err());
        fs::remove_dir_all(directory).unwrap();
    }
}
