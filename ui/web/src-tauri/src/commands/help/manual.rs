use jps_document_io::file_exports::{publish_export_pages, ExportFormat};
#[cfg(target_os = "linux")]
use std::ffi::OsStr;
use std::fs::{self, DirEntry};
use std::io;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Mutex as StdMutex, OnceLock};
use std::time::{SystemTime, UNIX_EPOCH};
#[cfg(not(debug_assertions))]
use tauri::path::BaseDirectory;
use tauri::{AppHandle, Manager};

static MANUAL_STAGING: OnceLock<StdMutex<Option<(PathBuf, PathBuf)>>> = OnceLock::new();
static MANUAL_STAGING_SEQUENCE: AtomicU64 = AtomicU64::new(0);

fn manual_filename(language: &str) -> &'static str {
    if language == "zh-CN" {
        "zh-CN.html"
    } else {
        "en.html"
    }
}

pub(crate) fn manual_pdf_filename(language: &str) -> &'static str {
    if language == "zh-CN" {
        "OctoPus-User-Manual-zh-CN.pdf"
    } else {
        "OctoPus-User-Manual-en.pdf"
    }
}

pub(super) fn manual_pdf_path(_app: &AppHandle, language: &str) -> Result<PathBuf, String> {
    let filename = manual_pdf_filename(language);
    #[cfg(debug_assertions)]
    let path = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../../../docs/PDF")
        .join(filename);
    #[cfg(not(debug_assertions))]
    let path = _app
        .path()
        .resolve(
            crate::resource_relative(&format!("docs/PDF/{filename}")),
            BaseDirectory::Resource,
        )
        .map_err(|error| format!("could not locate bundled user manual PDF: {error}"))?;
    if !path.is_file() {
        return Err(format!(
            "bundled user manual PDF is missing: {}",
            path.display()
        ));
    }
    Ok(path)
}

pub(crate) fn copy_manual_pdf(
    source: &Path,
    destination: &Path,
    confirmed_existing: &[PathBuf],
) -> Result<(), String> {
    let bytes =
        fs::read(source).map_err(|error| format!("could not read user manual PDF: {error}"))?;
    publish_export_pages(
        destination,
        ExportFormat::Pdf,
        &[&bytes],
        confirmed_existing,
    )
    .map_err(|error| format!("could not save user manual PDF: {error}"))?;
    Ok(())
}

fn manual_docs_path(_app: &AppHandle) -> Result<PathBuf, String> {
    #[cfg(debug_assertions)]
    let path = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../build/pdfjs-assets/docs");
    #[cfg(not(debug_assertions))]
    let path = _app
        .path()
        .resolve(crate::resource_relative("docs"), BaseDirectory::Resource)
        .map_err(|error| format!("could not locate bundled user manual: {error}"))?;
    if !path.is_dir() {
        return Err(format!(
            "bundled user manual resources are missing: {}",
            path.display()
        ));
    }
    Ok(path)
}

#[cfg(target_os = "linux")]
fn path_is_beneath(path: &Path, directory: &Path) -> bool {
    path.strip_prefix(directory)
        .is_ok_and(|relative| !relative.as_os_str().is_empty())
}

#[cfg(target_os = "linux")]
pub(crate) fn validated_appimage_docs_root(
    appimage: Option<&OsStr>,
    appdir: Option<&OsStr>,
    executable: &Path,
    resource_root: &Path,
) -> Option<PathBuf> {
    appimage?;
    let appdir = Path::new(appdir?).canonicalize().ok()?;
    let executable = executable.canonicalize().ok()?;
    let resource_root = resource_root.canonicalize().ok()?;
    if appdir.is_dir()
        && executable.is_file()
        && resource_root.is_dir()
        && path_is_beneath(&executable, &appdir)
        && path_is_beneath(&resource_root, &appdir)
    {
        Some(resource_root)
    } else {
        None
    }
}

fn running_appimage_docs_root(resource_root: &Path) -> Option<PathBuf> {
    #[cfg(target_os = "linux")]
    {
        let executable = std::env::current_exe().ok()?;
        validated_appimage_docs_root(
            std::env::var_os("APPIMAGE").as_deref(),
            std::env::var_os("APPDIR").as_deref(),
            &executable,
            resource_root,
        )
    }
    #[cfg(not(target_os = "linux"))]
    {
        let _ = resource_root;
        None
    }
}

pub(crate) fn manual_docs_match(source: &Path, candidate: &Path) -> io::Result<bool> {
    let source_type = fs::symlink_metadata(source)?.file_type();
    let candidate_type = fs::symlink_metadata(candidate)?.file_type();
    if !source_type.is_dir() || !candidate_type.is_dir() {
        return Ok(false);
    }

    let mut source_entries = fs::read_dir(source)?.collect::<Result<Vec<DirEntry>, _>>()?;
    let mut candidate_entries = fs::read_dir(candidate)?.collect::<Result<Vec<DirEntry>, _>>()?;
    source_entries.sort_by_key(DirEntry::file_name);
    candidate_entries.sort_by_key(DirEntry::file_name);
    if source_entries.len() != candidate_entries.len() {
        return Ok(false);
    }

    for (source_entry, candidate_entry) in source_entries.iter().zip(&candidate_entries) {
        if source_entry.file_name() != candidate_entry.file_name() {
            return Ok(false);
        }
        let source_path = source_entry.path();
        let candidate_path = candidate_entry.path();
        let source_type = source_entry.file_type()?;
        let candidate_type = candidate_entry.file_type()?;
        if source_type.is_dir() && candidate_type.is_dir() {
            if !manual_docs_match(&source_path, &candidate_path)? {
                return Ok(false);
            }
        } else if source_type.is_file() && candidate_type.is_file() {
            if fs::read(source_path)? != fs::read(candidate_path)? {
                return Ok(false);
            }
        } else {
            return Ok(false);
        }
    }
    Ok(true)
}

fn copy_directory_contents(source: &Path, destination: &Path) -> io::Result<()> {
    let mut entries = fs::read_dir(source)?.collect::<Result<Vec<DirEntry>, _>>()?;
    entries.sort_by_key(DirEntry::file_name);
    for entry in entries {
        let source_path = entry.path();
        let destination_path = destination.join(entry.file_name());
        let file_type = entry.file_type()?;
        if file_type.is_dir() {
            fs::create_dir(&destination_path)?;
            copy_directory_contents(&source_path, &destination_path)?;
        } else if file_type.is_file() {
            fs::copy(&source_path, &destination_path)?;
        } else {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                format!(
                    "unsupported manual resource entry: {}",
                    source_path.display()
                ),
            ));
        }
    }
    Ok(())
}

pub(crate) fn copy_manual_docs(source: &Path, destination: &Path) -> io::Result<()> {
    if !source.is_dir() {
        return Err(io::Error::new(
            io::ErrorKind::NotFound,
            format!("manual resource directory is missing: {}", source.display()),
        ));
    }
    fs::create_dir(destination)?;
    if let Err(error) = copy_directory_contents(source, destination) {
        return match fs::remove_dir_all(destination) {
            Ok(()) => Err(error),
            Err(cleanup_error) => Err(io::Error::new(
                cleanup_error.kind(),
                format!("{error}; could not remove incomplete manual copy: {cleanup_error}"),
            )),
        };
    }
    Ok(())
}

pub(crate) fn manual_staging_base(home_dir: &Path) -> PathBuf {
    home_dir.join("Downloads").join(".octopus.tmp")
}

pub(crate) fn find_matching_manual_docs(
    source: &Path,
    staging_base: &Path,
) -> io::Result<Option<PathBuf>> {
    let mut entries = fs::read_dir(staging_base)?.collect::<Result<Vec<DirEntry>, _>>()?;
    entries.sort_by_key(DirEntry::file_name);
    for entry in entries {
        if !entry
            .file_name()
            .to_string_lossy()
            .starts_with("octopus-manual-")
            || !entry.file_type()?.is_dir()
        {
            continue;
        }
        let candidate = entry.path();
        if manual_docs_match(source, &candidate).unwrap_or(false) {
            return Ok(Some(candidate));
        }
    }
    Ok(None)
}

fn manual_staging_candidate(base: &Path) -> PathBuf {
    let timestamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos();
    let sequence = MANUAL_STAGING_SEQUENCE.fetch_add(1, Ordering::Relaxed);
    base.join(format!(
        "octopus-manual-{}-{timestamp}-{sequence}",
        std::process::id()
    ))
}

pub(crate) fn stage_manual_docs(source: &Path, home_dir: &Path) -> Result<PathBuf, String> {
    let source = source
        .canonicalize()
        .map_err(|error| format!("could not locate bundled manual resources: {error}"))?;
    let base = manual_staging_base(home_dir);
    fs::create_dir_all(&base).map_err(|error| {
        format!(
            "could not create user manual staging directory {}: {error}",
            base.display()
        )
    })?;
    let cache = MANUAL_STAGING.get_or_init(|| StdMutex::new(None));
    let mut cached = cache.lock().unwrap_or_else(|error| error.into_inner());
    if let Some((cached_source, cached_destination)) = cached.as_ref() {
        if cached_source == &source
            && cached_destination.is_dir()
            && cached_destination.join("user-manual/en.html").is_file()
        {
            return Ok(cached_destination.clone());
        }
    }
    *cached = None;
    if let Some(destination) = find_matching_manual_docs(&source, &base).map_err(|error| {
        format!(
            "could not scan prior user manual copies in {}: {error}",
            base.display()
        )
    })? {
        *cached = Some((source, destination.clone()));
        return Ok(destination);
    }

    for _ in 0..16 {
        let destination = manual_staging_candidate(&base);
        match copy_manual_docs(&source, &destination) {
            Ok(()) => {
                *cached = Some((source, destination.clone()));
                return Ok(destination);
            }
            Err(error) if error.kind() == io::ErrorKind::AlreadyExists => continue,
            Err(error) => {
                return Err(format!(
                    "could not stage bundled user manual under {}: {error}",
                    base.display()
                ));
            }
        }
    }
    Err("could not create a unique user manual staging directory".into())
}

pub(crate) fn manual_html_path_from_root(resource_root: &Path, language: &str) -> PathBuf {
    resource_root
        .join("user-manual")
        .join(manual_filename(language))
}

pub(super) fn manual_html_path(app: &AppHandle, language: &str) -> Result<PathBuf, String> {
    let resource_root = manual_docs_path(app)?;
    let path = if let Some(appimage_root) = running_appimage_docs_root(&resource_root) {
        let home_dir = app
            .path()
            .home_dir()
            .map_err(|error| format!("could not locate user home for manual staging: {error}"))?;
        manual_html_path_from_root(&stage_manual_docs(&appimage_root, &home_dir)?, language)
    } else {
        manual_html_path_from_root(&resource_root, language)
    };
    if !path.is_file() {
        return Err(format!(
            "bundled user manual is missing: {}",
            path.display()
        ));
    }
    Ok(path)
}
