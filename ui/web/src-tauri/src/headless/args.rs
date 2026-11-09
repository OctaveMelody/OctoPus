use std::collections::HashMap;
use std::path::{Path, PathBuf};

use super::CliFailure;

pub(super) struct CliOptions {
    pub(super) operands: Vec<String>,
    values: HashMap<String, String>,
    flags: bool,
}

impl CliOptions {
    pub(super) fn value(&self, name: &str) -> Option<&String> {
        self.values.get(name)
    }

    pub(super) fn required_value(&self, name: &str, message: &str) -> Result<String, CliFailure> {
        self.value(name)
            .cloned()
            .ok_or_else(|| CliFailure::usage(message))
    }

    pub(super) fn required_path(&self, name: &str, message: &str) -> Result<PathBuf, CliFailure> {
        self.required_value(name, message).map(PathBuf::from)
    }

    pub(super) fn require_only(&self, accepted: &[&str]) -> Result<(), CliFailure> {
        for name in self.values.keys() {
            if !accepted.contains(&name.as_str()) {
                return Err(CliFailure::usage(format!("unknown option `--{name}`")));
            }
        }
        if self.flags && !accepted.contains(&"json") {
            return Err(CliFailure::usage("--json is not valid for this command"));
        }
        Ok(())
    }

    pub(super) fn require_no_operands(&self) -> Result<(), CliFailure> {
        if self.operands.is_empty() {
            Ok(())
        } else {
            Err(CliFailure::usage("capabilities does not accept a path"))
        }
    }
}

pub(super) fn parse_options(args: &[String]) -> Result<CliOptions, CliFailure> {
    let mut options = CliOptions {
        operands: Vec::new(),
        values: HashMap::new(),
        flags: false,
    };
    let mut index = 0;
    while index < args.len() {
        let arg = &args[index];
        if let Some(name) = arg.strip_prefix("--") {
            if name == "json" {
                if options.flags {
                    return Err(CliFailure::usage("--json may be provided only once"));
                }
                options.flags = true;
                index += 1;
                continue;
            }
            if name.is_empty() || options.values.contains_key(name) {
                return Err(CliFailure::usage(format!(
                    "invalid or repeated option `{arg}`"
                )));
            }
            let value = args
                .get(index + 1)
                .filter(|value| !value.starts_with("--"))
                .ok_or_else(|| CliFailure::usage(format!("option `{arg}` requires a value")))?;
            options.values.insert(name.to_owned(), value.clone());
            index += 2;
        } else {
            options.operands.push(arg.clone());
            index += 1;
        }
    }
    Ok(options)
}

pub(super) fn require_one_operand<'a>(
    options: &'a CliOptions,
    message: &str,
) -> Result<&'a str, CliFailure> {
    if options.operands.len() != 1 {
        return Err(CliFailure::usage(message));
    }
    Ok(&options.operands[0])
}

pub(super) fn resolve_input_path(value: &str, expected: &str) -> Result<PathBuf, CliFailure> {
    let path = absolute_path(Path::new(value))?;
    let canonical = path.canonicalize().map_err(|error| {
        CliFailure::input(
            "input_unavailable",
            format!("could not open input: {error}"),
        )
    })?;
    if !canonical.is_file() {
        return Err(CliFailure::input(
            "invalid_input_path",
            "input must be a regular file",
        ));
    }
    if expected == "jps" && !has_extension(&canonical, "jps") {
        return Err(CliFailure::input(
            "unsupported_input",
            "input must use the .jps extension",
        ));
    }
    Ok(canonical)
}

pub(super) fn resolve_output_path(value: PathBuf) -> Result<PathBuf, CliFailure> {
    let path = absolute_path(&value)?;
    let file_name = path
        .file_name()
        .filter(|name| !name.is_empty())
        .ok_or_else(|| CliFailure::input("invalid_output_path", "output path must name a file"))?;
    let parent = path
        .parent()
        .filter(|parent| !parent.as_os_str().is_empty())
        .unwrap_or(Path::new("."));
    let parent = absolute_path(parent)?;
    let canonical_parent = if parent.exists() {
        parent
            .canonicalize()
            .map_err(|error| CliFailure::input("invalid_output_path", error.to_string()))?
    } else {
        parent
    };
    Ok(canonical_parent.join(file_name))
}

pub(super) fn resolve_output_directory(value: &str) -> Result<PathBuf, CliFailure> {
    let path = absolute_path(Path::new(value))?;
    if path.exists() {
        let canonical = path
            .canonicalize()
            .map_err(|error| CliFailure::input("invalid_output_path", error.to_string()))?;
        if !canonical.is_dir() {
            return Err(CliFailure::input(
                "invalid_output_path",
                "--out-dir must be a directory",
            ));
        }
        Ok(canonical)
    } else {
        Ok(path)
    }
}

pub(super) fn has_extension(path: &Path, expected: &str) -> bool {
    path.extension()
        .and_then(|extension| extension.to_str())
        .is_some_and(|extension| extension.eq_ignore_ascii_case(expected))
}

fn absolute_path(path: &Path) -> Result<PathBuf, CliFailure> {
    if path.is_absolute() {
        Ok(path.to_path_buf())
    } else {
        std::env::current_dir()
            .map(|directory| directory.join(path))
            .map_err(|error| {
                CliFailure::execution("working_directory_unavailable", error.to_string())
            })
    }
}

#[cfg(test)]
mod tests {
    use super::{parse_options, resolve_output_path};

    #[test]
    fn flags_and_unicode_option_values_are_preserved() {
        let args = ["--out".into(), "简谱.jps".into(), "--json".into()];
        let options = parse_options(&args).expect("parse CLI options");
        assert_eq!(options.value("out").map(String::as_str), Some("简谱.jps"));
        assert!(options.flags);
    }

    #[test]
    fn output_paths_resolve_parent_segments_from_the_working_directory() {
        let directory = tempfile::tempdir().expect("temporary directory");
        std::fs::create_dir_all(directory.path().join("work")).expect("create work directory");
        std::fs::create_dir_all(directory.path().join("result")).expect("create result directory");
        let output = resolve_output_path(directory.path().join("work/../result/score.svg"))
            .expect("resolve output path");
        assert!(output.is_absolute());
        assert!(!output
            .components()
            .any(|component| { component == std::path::Component::ParentDir }));
        assert_eq!(
            output.file_name().and_then(|name| name.to_str()),
            Some("score.svg")
        );
        assert_eq!(
            output
                .parent()
                .and_then(|parent| parent.file_name())
                .and_then(|name| name.to_str()),
            Some("result")
        );
    }

    #[cfg(unix)]
    #[test]
    fn output_parent_resolution_preserves_symlink_and_parent_traversal() {
        use std::os::unix::fs::symlink;

        let directory = tempfile::tempdir().expect("temporary directory");
        let real = directory.path().join("real");
        std::fs::create_dir_all(real.join("child")).expect("create real directory");
        let alias = directory.path().join("alias");
        symlink(real.join("child"), &alias).expect("create symlink");

        let output = resolve_output_path(alias.join("../score.svg")).expect("resolve output");

        assert_eq!(output.parent(), Some(real.as_path()));
    }
}
