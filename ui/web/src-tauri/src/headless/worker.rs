use std::path::{Path, PathBuf};

use jps_document_io::file_exports::ExportFormat;
use jps_engine_bridge::EngineSupervisor;

use super::CliFailure;

pub(super) fn engine_supervisor() -> Result<EngineSupervisor, CliFailure> {
    #[cfg(debug_assertions)]
    {
        Ok(EngineSupervisor::default())
    }
    #[cfg(not(debug_assertions))]
    {
        let executable = std::env::current_exe().map_err(|error| {
            CliFailure::capability(
                "worker_unavailable",
                format!("could not locate application executable: {error}"),
            )
        })?;
        let directory = executable.parent().ok_or_else(|| {
            CliFailure::capability(
                "worker_unavailable",
                "application executable has no parent directory",
            )
        })?;
        let worker_name = if cfg!(windows) {
            "octopus-engine.exe"
        } else {
            "octopus-engine"
        };
        let worker = packaged_worker_path(directory, worker_name);
        if !worker.is_file() {
            return Err(CliFailure::capability(
                "worker_unavailable",
                format!("packaged Python worker is missing at {}", worker.display()),
            ));
        }
        Ok(EngineSupervisor::packaged(worker))
    }
}

#[cfg(not(debug_assertions))]
fn packaged_worker_path(directory: &Path, worker_name: &str) -> PathBuf {
    if cfg!(target_os = "linux") {
        directory.join("../lib/OctoPus/engine").join(worker_name)
    } else if cfg!(target_os = "macos") {
        directory
            .join("../Resources/lib/OctoPus/engine")
            .join(worker_name)
    } else {
        directory.join("lib/OctoPus/engine").join(worker_name)
    }
}

pub(super) fn executable_on_path(name: &str) -> bool {
    let Some(path) = std::env::var_os("PATH") else {
        return false;
    };
    #[cfg(windows)]
    let names = {
        let pathext = std::env::var_os("PATHEXT").unwrap_or_else(|| ".COM;.EXE;.BAT;.CMD".into());
        let mut extensions = pathext
            .to_string_lossy()
            .split(';')
            .filter(|extension| !extension.is_empty())
            .map(str::to_owned)
            .collect::<Vec<_>>();
        extensions.insert(0, String::new());
        extensions
            .into_iter()
            .map(|extension| PathBuf::from(format!("{name}{extension}")))
            .collect::<Vec<_>>()
    };
    #[cfg(not(windows))]
    let names = [PathBuf::from(name)];
    std::env::split_paths(&path).any(|directory| {
        names
            .iter()
            .any(|candidate| is_executable(&directory.join(candidate)))
    })
}

#[cfg(windows)]
fn is_executable(path: &Path) -> bool {
    path.is_file()
}

#[cfg(unix)]
fn is_executable(path: &Path) -> bool {
    use std::os::unix::fs::PermissionsExt;
    path.metadata()
        .is_ok_and(|metadata| metadata.is_file() && metadata.permissions().mode() & 0o111 != 0)
}

#[cfg(not(any(windows, unix)))]
fn is_executable(path: &Path) -> bool {
    path.is_file()
}

pub(super) fn format_extension(format: ExportFormat) -> &'static str {
    match format {
        ExportFormat::Svg => "svg",
        ExportFormat::Pdf => "pdf",
        ExportFormat::Jpg => "jpg",
        ExportFormat::Png => "png",
    }
}

pub(super) fn path_string(path: &Path) -> Result<String, CliFailure> {
    path.to_str()
        .map(str::to_owned)
        .ok_or_else(|| CliFailure::input("invalid_path_encoding", "path is not valid UTF-8"))
}
