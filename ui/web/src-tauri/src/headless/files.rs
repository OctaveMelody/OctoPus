use std::fs;
use std::io::{self, Write};
use std::path::{Path, PathBuf};

use same_file::Handle;
use tempfile::NamedTempFile;

use super::CliFailure;

pub(super) fn ensure_parent(path: &Path) -> Result<(), CliFailure> {
    let parent = path.parent().ok_or_else(|| {
        CliFailure::input("invalid_output_path", "output path has no parent directory")
    })?;
    fs::create_dir_all(parent).map_err(|error| {
        CliFailure::execution(
            "output_directory_failed",
            format!("could not create output directory: {error}"),
        )
    })
}

pub(super) fn reject_existing_outputs(paths: &[PathBuf]) -> Result<(), CliFailure> {
    for path in paths {
        match fs::symlink_metadata(path) {
            Ok(_) => {
                return Err(CliFailure::input(
                    "output_exists",
                    format!("output already exists: {}", path.display()),
                ));
            }
            Err(error) if error.kind() == io::ErrorKind::NotFound => {}
            Err(error) => {
                return Err(CliFailure::input("output_path_invalid", error.to_string()));
            }
        }
    }
    Ok(())
}

struct StagedOutput {
    target: PathBuf,
    temporary: NamedTempFile,
    identity: Handle,
}

pub(super) fn publish_new_files(
    outputs: Vec<(PathBuf, Vec<u8>)>,
) -> Result<Vec<PathBuf>, CliFailure> {
    let mut staged = Vec::with_capacity(outputs.len());
    for (target, bytes) in outputs {
        ensure_parent(&target)?;
        let parent = target.parent().ok_or_else(|| {
            CliFailure::input("invalid_output_path", "output path has no parent directory")
        })?;
        let mut temporary = NamedTempFile::new_in(parent)
            .map_err(|error| CliFailure::execution("output_stage_failed", error.to_string()))?;
        temporary
            .write_all(&bytes)
            .and_then(|()| temporary.as_file().sync_all())
            .map_err(|error| CliFailure::execution("output_stage_failed", error.to_string()))?;
        let identity =
            Handle::from_file(temporary.as_file().try_clone().map_err(|error| {
                CliFailure::execution("output_stage_failed", error.to_string())
            })?)
            .map_err(|error| CliFailure::execution("output_stage_failed", error.to_string()))?;
        staged.push(StagedOutput {
            target,
            temporary,
            identity,
        });
    }

    let mut published: Vec<(PathBuf, Handle)> = Vec::new();
    for output in staged {
        let target = output.target.clone();
        match output.temporary.persist_noclobber(&target) {
            Ok(file) => {
                drop(file);
                published.push((target, output.identity));
            }
            Err(error) => {
                let already_exists = error.error.kind() == io::ErrorKind::AlreadyExists;
                let publish_error = error.error.to_string();
                drop(error.file);
                if !rollback_outputs(&published) {
                    return Err(CliFailure::execution(
                        "partial_output",
                        "a partial output could not be rolled back; inspect the output paths before retrying",
                    ));
                }
                if already_exists {
                    return Err(CliFailure::input(
                        "output_exists",
                        format!("output already exists: {}", target.display()),
                    ));
                }
                return Err(CliFailure::execution(
                    "output_publish_failed",
                    format!("could not publish output: {publish_error}"),
                ));
            }
        }
    }
    Ok(published.into_iter().map(|(target, _)| target).collect())
}

fn rollback_outputs(published: &[(PathBuf, Handle)]) -> bool {
    let mut complete = true;
    for (path, identity) in published.iter().rev() {
        match Handle::from_path(path) {
            Ok(current) if current == *identity => {
                if let Err(error) = fs::remove_file(path) {
                    if error.kind() != io::ErrorKind::NotFound {
                        complete = false;
                    }
                }
            }
            Ok(_) | Err(_) => complete = false,
        }
    }
    complete
}

#[cfg(test)]
mod tests {
    use std::fs;

    use super::publish_new_files;

    #[test]
    fn publishes_all_distinct_outputs() {
        let directory = tempfile::tempdir().expect("temporary directory");
        let draft = directory.path().join("draft.jps");
        let issues = directory.path().join("issues.json");

        let outputs = publish_new_files(vec![
            (draft.clone(), b"Q: 1 |".to_vec()),
            (issues.clone(), b"{\"issues\":[]}".to_vec()),
        ])
        .expect("publish outputs");

        assert_eq!(outputs, [draft.clone(), issues.clone()]);
        assert_eq!(fs::read(draft).expect("read draft"), b"Q: 1 |");
        assert_eq!(fs::read(issues).expect("read issues"), b"{\"issues\":[]}");
        assert_eq!(fs::read_dir(directory.path()).unwrap().count(), 2);
    }

    #[test]
    fn failed_second_publish_rolls_back_the_first_without_replacing_existing_data() {
        let directory = tempfile::tempdir().expect("temporary directory");
        let draft = directory.path().join("draft.jps");
        let issues = directory.path().join("issues.json");
        fs::write(&issues, "keep me").expect("write existing destination");

        let error = publish_new_files(vec![
            (draft.clone(), b"new draft".to_vec()),
            (issues.clone(), b"new issues".to_vec()),
        ])
        .expect_err("existing destination must fail");

        assert_eq!(error.code, "output_exists");
        assert!(!draft.exists());
        assert_eq!(fs::read_to_string(issues).unwrap(), "keep me");
        assert_eq!(fs::read_dir(directory.path()).unwrap().count(), 1);
    }
}
