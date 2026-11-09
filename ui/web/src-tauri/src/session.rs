//! Cross-process coordination for GUI editing sessions and headless input snapshots.
//!
//! The registry is intentionally stored in the same per-user data directory in both modes.
//! Every registry operation and every headless input read uses an OS advisory lock. Owner
//! lease files are locked for the lifetime of a GUI process, so a crash releases its sessions.

use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::fs::{self, File, OpenOptions};
use std::io::{self, Read, Write};
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex, OnceLock};
use std::time::{SystemTime, UNIX_EPOCH};
use tempfile::NamedTempFile;

const PRODUCT_IDENTIFIER: &str = "org.octopus.desktop";
const REGISTRY_LIMIT: u64 = 4 * 1024 * 1024;
const MAX_JPS_BYTES: u64 = 8 * 1024 * 1024;
const MAX_REFERENCE_BYTES: u64 = 100 * 1024 * 1024;

#[derive(Clone)]
pub(crate) struct SessionCoordinator(Arc<CoordinatorInner>);

struct CoordinatorInner {
    root: PathBuf,
    owner_id: String,
    _owner_lock: File,
    local_lock: Mutex<()>,
    local_asset_lock: Mutex<()>,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub(crate) struct SessionOwner {
    pub window_label: String,
    pub document_name: String,
    pub dirty: bool,
    pub conflict_latched: bool,
    pub process_id: u32,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub(crate) struct SessionConflict {
    pub path: String,
    pub sessions: Vec<SessionOwner>,
}

#[derive(Debug)]
pub(crate) enum SessionError {
    Conflict(SessionConflict),
    Io(String),
    InvalidInput(String),
    RegistryUnavailable(String),
}

impl std::fmt::Display for SessionError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Conflict(conflict) => write!(
                formatter,
                "input is being edited in {} open session(s)",
                conflict.sessions.len()
            ),
            Self::Io(message)
            | Self::InvalidInput(message)
            | Self::RegistryUnavailable(message) => formatter.write_str(message),
        }
    }
}

impl std::error::Error for SessionError {}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
struct EditorSession {
    owner_id: String,
    process_id: u32,
    window_label: String,
    document_id: String,
    document_name: String,
    dirty: bool,
    document_path: Option<String>,
    reference_ids: Vec<String>,
    retained_reference_ids: Vec<String>,
    conflict_latched_paths: Vec<String>,
}

#[derive(Default, Serialize, Deserialize)]
struct Registry {
    sessions: Vec<EditorSession>,
    /// Original user-selected paths for staged reference asset IDs. The staged cache file is
    /// only an implementation detail and must never become the visible input identity.
    reference_origins: BTreeMap<String, ReferenceOrigin>,
    window_sequences: BTreeMap<String, WindowSequence>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
struct ReferenceOrigin {
    path: String,
    owner_id: String,
    pending: bool,
}

#[derive(Clone, Copy, Debug, Serialize, Deserialize)]
struct WindowSequence {
    generation: u64,
    sequence: u64,
}

impl SessionCoordinator {
    /// Construct a coordinator rooted at Tauri's `app_data_dir()` or the identical CLI path.
    pub(crate) fn for_data_directory(path: &Path) -> Result<Self, SessionError> {
        fs::create_dir_all(path).map_err(session_io)?;
        let root = path.join("file-sessions");
        let owners = root.join("owners");
        fs::create_dir_all(&owners).map_err(session_io)?;
        let registry_lock = acquire_registry_lock(&root)?;
        let owner_id = unique_id();
        let owner_path = owners.join(format!("{owner_id}.lock"));
        let owner_lock = OpenOptions::new()
            .read(true)
            .write(true)
            .create_new(true)
            .open(owner_path)
            .map_err(session_io)?;
        lock_file(&owner_lock, true).map_err(session_io)?;
        let coordinator = Self(Arc::new(CoordinatorInner {
            root,
            owner_id,
            _owner_lock: owner_lock,
            local_lock: Mutex::new(()),
            local_asset_lock: Mutex::new(()),
        }));
        drop(registry_lock);
        Ok(coordinator)
    }

    /// Register or replace one editor's current source identity. Input paths must already have
    /// been selected or saved by native document commands; staged reference IDs resolve only to
    /// source paths recorded by `stage_reference_assets`.
    pub(crate) fn update_editor(
        &self,
        window_label: &str,
        document_id: &str,
        document_name: &str,
        document_path: Option<&Path>,
        reference_ids: &[String],
        retained_reference_ids: &[String],
        dirty: bool,
        generation: u64,
        sequence: u64,
    ) -> Result<(), SessionError> {
        if window_label.is_empty()
            || document_id.is_empty()
            || document_name.trim().is_empty()
            || generation == 0
            || generation > 9_007_199_254_740_991
            || sequence == 0
            || sequence > 9_007_199_254_740_991
        {
            return Err(SessionError::InvalidInput(
                "editor session identity is invalid".into(),
            ));
        }
        let owner_id = self.0.owner_id.clone();
        let process_id = std::process::id();
        let window_label = window_label.to_owned();
        let document_id = document_id.to_owned();
        let document_name = document_name.to_owned();
        let document_path = document_path.map(Path::to_path_buf);
        let reference_ids = reference_ids.to_vec();
        let retained_reference_ids = retained_reference_ids.to_vec();
        self.with_asset_lock(|| {
            self.with_registry(move |registry| {
                let key = window_key(&owner_id, &window_label);
                if registry.window_sequences.get(&key).is_some_and(|previous| {
                    generation < previous.generation
                        || (generation == previous.generation && sequence <= previous.sequence)
                }) {
                    return Ok(());
                }
                registry.window_sequences.insert(
                    key,
                    WindowSequence {
                        generation,
                        sequence,
                    },
                );
                let conflict_latched_paths = registry
                    .sessions
                    .iter()
                    .filter(|session| {
                        session.owner_id == owner_id
                            && session.window_label == window_label
                            && session.document_id == document_id
                    })
                    .flat_map(|session| session.conflict_latched_paths.iter().cloned())
                    .collect::<Vec<_>>();
                registry.sessions.retain(|session| {
                    !(session.owner_id == owner_id && session.window_label == window_label)
                });
                let document_path = document_path
                    .as_deref()
                    .filter(|path| path.exists())
                    .map(canonical_identity)
                    .transpose()?;
                let mut reference_ids = reference_ids;
                reference_ids.sort();
                reference_ids.dedup();
                let mut retained_reference_ids = retained_reference_ids;
                retained_reference_ids.sort();
                retained_reference_ids.dedup();
                registry.sessions.push(EditorSession {
                    owner_id,
                    process_id,
                    window_label,
                    document_id,
                    document_name,
                    dirty,
                    document_path,
                    reference_ids,
                    retained_reference_ids,
                    conflict_latched_paths,
                });
                let active_ids = registry
                    .sessions
                    .iter()
                    .flat_map(|session| {
                        session
                            .reference_ids
                            .iter()
                            .chain(&session.retained_reference_ids)
                            .cloned()
                    })
                    .collect::<std::collections::HashSet<_>>();
                for (id, origin) in &mut registry.reference_origins {
                    if active_ids.contains(id) {
                        origin.pending = false;
                    }
                }
                Ok(())
            })
        })
    }

    pub(crate) fn close_editor(
        &self,
        window_label: &str,
        generation: u64,
        sequence: u64,
    ) -> Result<(), SessionError> {
        let owner_id = self.0.owner_id.clone();
        let window_label = window_label.to_owned();
        if generation == 0
            || generation > 9_007_199_254_740_991
            || sequence == 0
            || sequence > 9_007_199_254_740_991
        {
            return Err(SessionError::InvalidInput(
                "editor session sequence is invalid".into(),
            ));
        }
        self.with_asset_lock(|| {
            self.with_registry(move |registry| {
                let key = window_key(&owner_id, &window_label);
                if registry.window_sequences.get(&key).is_some_and(|previous| {
                    generation < previous.generation
                        || (generation == previous.generation && sequence <= previous.sequence)
                }) {
                    return Ok(());
                }
                registry.window_sequences.insert(
                    key,
                    WindowSequence {
                        generation,
                        sequence,
                    },
                );
                registry.sessions.retain(|session| {
                    !(session.owner_id == owner_id && session.window_label == window_label)
                });
                Ok(())
            })
        })
    }

    /// Serialize an atomic document write with headless snapshot acquisition, then reserve the
    /// saved path as dirty until the frontend reports the save's final revision.
    pub(crate) fn coordinate_save<T>(
        &self,
        window_label: &str,
        document_id: &str,
        document_name: &str,
        target: &Path,
        write: impl FnOnce() -> Result<T, String>,
    ) -> Result<T, SessionError> {
        let owner_id = self.0.owner_id.clone();
        let process_id = std::process::id();
        let window_label = window_label.to_owned();
        let document_id = document_id.to_owned();
        let document_name = document_name.to_owned();
        let target = target.to_path_buf();
        self.with_registry(move |registry| {
            let value = write().map_err(SessionError::Io)?;
            let identity = canonical_identity(&target)?;
            if let Some(session) = registry.sessions.iter_mut().find(|session| {
                session.owner_id == owner_id
                    && session.window_label == window_label
                    && session.document_id == document_id
            }) {
                session.document_name = document_name.clone();
                session.document_path = Some(identity);
                session.dirty = true;
            } else {
                registry.sessions.push(EditorSession {
                    owner_id,
                    process_id,
                    window_label,
                    document_id,
                    document_name,
                    dirty: true,
                    document_path: Some(identity),
                    reference_ids: Vec::new(),
                    retained_reference_ids: Vec::new(),
                    conflict_latched_paths: Vec::new(),
                });
            }
            Ok(value)
        })
    }

    pub(crate) fn coordinate_reference_stage<T>(
        &self,
        stage: impl FnOnce() -> Result<(T, Vec<(String, PathBuf)>), String>,
    ) -> Result<T, SessionError> {
        let owner_id = self.0.owner_id.clone();
        self.with_asset_lock(|| {
            let (value, origins) = stage().map_err(SessionError::Io)?;
            self.with_registry(move |registry| {
                for (id, source_path) in origins {
                    if id.is_empty() || id.len() > 255 {
                        return Err(SessionError::InvalidInput(
                            "reference identity is invalid".into(),
                        ));
                    }
                    registry.reference_origins.insert(
                        id,
                        ReferenceOrigin {
                            path: canonical_identity(&source_path)?,
                            owner_id: owner_id.clone(),
                            pending: true,
                        },
                    );
                }
                Ok(())
            })?;
            Ok(value)
        })
    }

    pub(crate) fn coordinate_reference_prune<T>(
        &self,
        requested_ids: &[String],
        prune: impl FnOnce(&[String]) -> Result<T, String>,
    ) -> Result<T, SessionError> {
        let requested = requested_ids
            .iter()
            .cloned()
            .collect::<std::collections::HashSet<_>>();
        self.with_asset_lock(|| {
            let retained = self.with_registry(|registry| {
                let mut retained = requested.clone();
                retained.extend(registry.sessions.iter().flat_map(|session| {
                    session
                        .reference_ids
                        .iter()
                        .chain(&session.retained_reference_ids)
                        .cloned()
                }));
                for (id, origin) in &registry.reference_origins {
                    if origin.pending
                        && owner_is_live(&self.0.root, &self.0.owner_id, &origin.owner_id)?
                    {
                        retained.insert(id.clone());
                    }
                }
                Ok(retained.into_iter().collect::<Vec<_>>())
            })?;
            let result = prune(&retained).map_err(SessionError::Io)?;
            self.with_registry(move |registry| {
                let retained = retained
                    .into_iter()
                    .collect::<std::collections::HashSet<_>>();
                registry
                    .reference_origins
                    .retain(|id, _| retained.contains(id));
                for session in &mut registry.sessions {
                    session.reference_ids.retain(|id| retained.contains(id));
                    session
                        .retained_reference_ids
                        .retain(|id| retained.contains(id));
                }
                Ok(())
            })?;
            Ok(result)
        })
    }

    pub(crate) fn coordinate_reference_discard<T>(
        &self,
        ids: &[String],
        discard: impl FnOnce(&[String]) -> Result<T, String>,
    ) -> Result<T, SessionError> {
        let requested = ids
            .iter()
            .cloned()
            .collect::<std::collections::HashSet<_>>();
        let owner_id = self.0.owner_id.clone();
        self.with_asset_lock(|| {
            let removable = self.with_registry(|registry| {
                let active = registry
                    .sessions
                    .iter()
                    .flat_map(|session| {
                        session
                            .reference_ids
                            .iter()
                            .chain(&session.retained_reference_ids)
                            .cloned()
                    })
                    .collect::<std::collections::HashSet<_>>();
                Ok(requested
                    .iter()
                    .filter(|id| {
                        !active.contains(*id)
                            && registry
                                .reference_origins
                                .get(*id)
                                .is_some_and(|origin| origin.owner_id == owner_id)
                    })
                    .cloned()
                    .collect::<Vec<_>>())
            })?;
            let result = discard(&removable).map_err(SessionError::Io)?;
            self.with_registry(move |registry| {
                let removed = removable
                    .into_iter()
                    .collect::<std::collections::HashSet<_>>();
                registry
                    .reference_origins
                    .retain(|id, _| !removed.contains(id));
                Ok(())
            })?;
            Ok(result)
        })
    }

    /// Read the exact bytes a headless job will process while holding the same cross-process
    /// lock used by GUI edit-state changes. A clean open file is read from disk; any dirty alias
    /// returns a structured conflict before bytes are read.
    pub(crate) fn read_input_snapshot(&self, path: &Path) -> Result<Vec<u8>, SessionError> {
        let expected_max = input_size_limit(path)?;
        let input = canonical_input(path)?;
        let file = self.with_registry(|registry| {
            let origins = registry.reference_origins.clone();
            let mut conflicts = Vec::new();
            for session in &mut registry.sessions {
                let same_input = session_matches_input(session, &origins, &input);
                let was_latched = session
                    .conflict_latched_paths
                    .iter()
                    .any(|identity| identities_match(Path::new(identity), &input));
                if was_latched || (same_input && session.dirty) {
                    if session.dirty {
                        session.conflict_latched_paths.push(path_identity(&input));
                        session.conflict_latched_paths.sort();
                        session.conflict_latched_paths.dedup();
                    }
                    conflicts.push(SessionOwner {
                        window_label: session.window_label.clone(),
                        document_name: session.document_name.clone(),
                        dirty: session.dirty,
                        conflict_latched: true,
                        process_id: session.process_id,
                    });
                }
            }
            if !conflicts.is_empty() {
                return Err(SessionError::Conflict(SessionConflict {
                    path: input.to_string_lossy().into_owned(),
                    sessions: conflicts,
                }));
            }
            let file = File::open(&input).map_err(session_io)?;
            let metadata = file.metadata().map_err(session_io)?;
            if !metadata.is_file() {
                return Err(SessionError::InvalidInput(
                    "input must be a regular file".into(),
                ));
            }
            if metadata.len() > expected_max {
                return Err(SessionError::InvalidInput(format!(
                    "input exceeds the {expected_max}-byte limit"
                )));
            }
            Ok(file)
        })?;
        let mut bytes = Vec::new();
        file.take(expected_max + 1)
            .read_to_end(&mut bytes)
            .map_err(session_io)?;
        if bytes.len() as u64 > expected_max {
            return Err(SessionError::InvalidInput(format!(
                "input exceeds the {expected_max}-byte limit"
            )));
        }
        Ok(bytes)
    }

    fn with_registry<T>(
        &self,
        operation: impl FnOnce(&mut Registry) -> Result<T, SessionError>,
    ) -> Result<T, SessionError> {
        let _local = self.0.local_lock.lock().map_err(|_| {
            SessionError::RegistryUnavailable("file session registry is unavailable".into())
        })?;
        let _registry_lock = acquire_registry_lock(&self.0.root)?;
        let registry_path = self.0.root.join("registry.json");
        let mut registry = read_registry(&registry_path)?;
        prune_dead_owners(&self.0.root, &self.0.owner_id, &mut registry)?;
        let result = operation(&mut registry);
        write_registry(&self.0.root, &registry)?;
        result
    }

    fn with_asset_lock<T>(
        &self,
        operation: impl FnOnce() -> Result<T, SessionError>,
    ) -> Result<T, SessionError> {
        let _local = self.0.local_asset_lock.lock().map_err(|_| {
            SessionError::RegistryUnavailable("reference asset coordination is unavailable".into())
        })?;
        let path = self.0.root.join("reference-assets.lock");
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .open(path)
            .map_err(session_io)?;
        let _lock = FileLock::acquire(file).map_err(session_io)?;
        operation()
    }
}

#[tauri::command]
pub(crate) fn sync_editor_session(
    window: tauri::WebviewWindow,
    coordinator: tauri::State<'_, SessionCoordinator>,
    selected_files: tauri::State<'_, jps_document_io::SelectedJpsFiles>,
    document_id: String,
    document_name: String,
    path: Option<String>,
    reference_ids: Vec<String>,
    retained_reference_ids: Vec<String>,
    dirty: bool,
    generation: u64,
    sequence: u64,
) -> Result<(), String> {
    let selected_path = match path {
        Some(path) => {
            let path = PathBuf::from(path);
            if !selected_files.allows(&path)? {
                return Err("editor session path was not selected or saved by this app".into());
            }
            Some(path)
        }
        None => None,
    };
    coordinator
        .update_editor(
            window.label(),
            &document_id,
            &document_name,
            selected_path.as_deref(),
            &reference_ids,
            &retained_reference_ids,
            dirty,
            generation,
            sequence,
        )
        .map_err(|error| error.to_string())
}

#[tauri::command]
pub(crate) fn close_editor_session(
    window: tauri::WebviewWindow,
    coordinator: tauri::State<'_, SessionCoordinator>,
    generation: u64,
    sequence: u64,
) -> Result<(), String> {
    coordinator
        .close_editor(window.label(), generation, sequence)
        .map_err(|error| error.to_string())
}

/// Headless entry point uses Tauri's platform data-dir convention and product identifier.
pub(crate) fn read_input_snapshot(path: &Path) -> Result<Vec<u8>, SessionError> {
    default_coordinator()?.read_input_snapshot(path)
}

fn session_matches_input(
    session: &EditorSession,
    origins: &BTreeMap<String, ReferenceOrigin>,
    input: &Path,
) -> bool {
    session
        .document_path
        .as_deref()
        .is_some_and(|identity| identities_match(Path::new(identity), input))
        || session.reference_ids.iter().any(|id| {
            origins
                .get(id)
                .is_some_and(|origin| identities_match(Path::new(&origin.path), input))
        })
}

fn window_key(owner_id: &str, window_label: &str) -> String {
    format!("{owner_id}\0{window_label}")
}

fn default_coordinator() -> Result<&'static SessionCoordinator, SessionError> {
    static COORDINATOR: OnceLock<Result<SessionCoordinator, String>> = OnceLock::new();
    match COORDINATOR.get_or_init(|| {
        let path =
            user_data_directory().ok_or_else(|| "user data directory is unavailable".to_owned())?;
        SessionCoordinator::for_data_directory(&path).map_err(|error| error.to_string())
    }) {
        Ok(coordinator) => Ok(coordinator),
        Err(message) => Err(SessionError::RegistryUnavailable(message.clone())),
    }
}

/// Matches `tauri::PathResolver::app_data_dir()` for the desktop's configured identifier.
pub(crate) fn user_data_directory() -> Option<PathBuf> {
    dirs::data_dir().map(|path| path.join(PRODUCT_IDENTIFIER))
}

fn input_size_limit(path: &Path) -> Result<u64, SessionError> {
    match path
        .extension()
        .and_then(|extension| extension.to_str())
        .unwrap_or_default()
        .to_ascii_lowercase()
        .as_str()
    {
        "jps" => Ok(MAX_JPS_BYTES),
        "png" | "jpg" | "jpeg" | "pdf" => Ok(MAX_REFERENCE_BYTES),
        _ => Err(SessionError::InvalidInput(
            "unsupported input file type".into(),
        )),
    }
}

fn canonical_input(path: &Path) -> Result<PathBuf, SessionError> {
    let canonical = fs::canonicalize(path).map_err(session_io)?;
    let metadata = fs::metadata(&canonical).map_err(session_io)?;
    if !metadata.is_file() {
        return Err(SessionError::InvalidInput(
            "input must be a regular file".into(),
        ));
    }
    Ok(canonical)
}

fn canonical_identity(path: &Path) -> Result<String, SessionError> {
    let canonical = canonical_input(path)?;
    Ok(path_identity(&canonical))
}

fn path_identity(path: &Path) -> String {
    let identity = path.to_string_lossy().into_owned();
    #[cfg(target_os = "windows")]
    return identity.to_lowercase();
    #[cfg(not(target_os = "windows"))]
    identity
}

fn identities_match(left: &Path, right: &Path) -> bool {
    if path_identity(left) == path_identity(right) {
        return true;
    }
    same_file::is_same_file(left, right).unwrap_or(false)
}

fn read_registry(path: &Path) -> Result<Registry, SessionError> {
    let bytes = match fs::read(path) {
        Ok(bytes) => bytes,
        Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(Registry::default()),
        Err(error) => return Err(session_io(error)),
    };
    if bytes.len() as u64 > REGISTRY_LIMIT {
        return Err(SessionError::RegistryUnavailable(
            "file session registry exceeds its size limit".into(),
        ));
    }
    serde_json::from_slice(&bytes).map_err(|error| {
        SessionError::RegistryUnavailable(format!("file session registry is invalid: {error}"))
    })
}

fn write_registry(root: &Path, registry: &Registry) -> Result<(), SessionError> {
    let bytes = serde_json::to_vec(registry)
        .map_err(|error| SessionError::RegistryUnavailable(error.to_string()))?;
    if bytes.len() as u64 > REGISTRY_LIMIT {
        return Err(SessionError::RegistryUnavailable(
            "file session registry exceeds its size limit".into(),
        ));
    }
    let path = root.join("registry.json");
    let mut temporary = NamedTempFile::new_in(root).map_err(session_io)?;
    temporary.write_all(&bytes).map_err(session_io)?;
    temporary.as_file().sync_all().map_err(session_io)?;
    temporary
        .persist(&path)
        .map_err(|error| session_io(error.error))?;
    Ok(())
}

fn prune_dead_owners(
    root: &Path,
    current_owner: &str,
    registry: &mut Registry,
) -> Result<(), SessionError> {
    let mut live = std::collections::HashSet::new();
    let owners = root.join("owners");
    for entry in fs::read_dir(&owners).map_err(session_io)? {
        let entry = entry.map_err(session_io)?;
        if entry.path().file_stem().and_then(|stem| stem.to_str()) == Some(current_owner) {
            live.insert(current_owner.to_owned());
            continue;
        }
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .open(entry.path())
            .map_err(session_io)?;
        match lock_file(&file, false) {
            Ok(()) => {
                unlock_file(&file).map_err(session_io)?;
                let _ = fs::remove_file(entry.path());
            }
            Err(error) if error.kind() == io::ErrorKind::WouldBlock => {
                if let Some(owner) = entry.path().file_stem().and_then(|stem| stem.to_str()) {
                    live.insert(owner.to_owned());
                }
            }
            Err(error) => return Err(session_io(error)),
        }
    }
    registry
        .sessions
        .retain(|session| live.contains(&session.owner_id));
    registry.window_sequences.retain(|key, _| {
        key.split_once('\0')
            .is_some_and(|(owner, _)| live.contains(owner))
    });
    Ok(())
}

fn owner_is_live(root: &Path, current_owner: &str, owner_id: &str) -> Result<bool, SessionError> {
    if owner_id == current_owner {
        return Ok(true);
    }
    let path = root.join("owners").join(format!("{owner_id}.lock"));
    let file = match OpenOptions::new().read(true).write(true).open(path) {
        Ok(file) => file,
        Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(false),
        Err(error) => return Err(session_io(error)),
    };
    match lock_file(&file, false) {
        Ok(()) => {
            unlock_file(&file).map_err(session_io)?;
            Ok(false)
        }
        Err(error) if error.kind() == io::ErrorKind::WouldBlock => Ok(true),
        Err(error) => Err(session_io(error)),
    }
}

fn unique_id() -> String {
    let time = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos();
    format!(
        "{:x}-{:x}-{:x}",
        std::process::id(),
        time,
        NEXT_ID.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
    )
}

static NEXT_ID: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(1);

fn session_io(error: io::Error) -> SessionError {
    SessionError::Io(error.to_string())
}

struct FileLock(File);

impl FileLock {
    fn acquire(file: File) -> io::Result<Self> {
        lock_file(&file, true)?;
        Ok(Self(file))
    }
}

impl Drop for FileLock {
    fn drop(&mut self) {
        let _ = unlock_file(&self.0);
    }
}

fn acquire_registry_lock(root: &Path) -> Result<FileLock, SessionError> {
    let path = root.join("registry.lock");
    let file = OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .open(path)
        .map_err(session_io)?;
    FileLock::acquire(file).map_err(session_io)
}

fn lock_file(file: &File, wait: bool) -> io::Result<()> {
    if wait {
        file.lock()
    } else {
        match file.try_lock() {
            Ok(()) => Ok(()),
            Err(std::fs::TryLockError::WouldBlock) => Err(io::Error::new(
                io::ErrorKind::WouldBlock,
                "file session is active",
            )),
            Err(std::fs::TryLockError::Error(error)) => Err(error),
        }
    }
}

fn unlock_file(file: &File) -> io::Result<()> {
    file.unlock()
}
