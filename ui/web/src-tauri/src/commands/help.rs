use serde::{Deserialize, Serialize};
use std::path::PathBuf;
use std::time::Duration;
#[cfg(not(debug_assertions))]
use tauri::path::BaseDirectory;
use tauri::AppHandle;
#[cfg(not(debug_assertions))]
use tauri::Manager;
use tauri_plugin_opener::OpenerExt;

const PROJECT: &str = "https://github.com/OctaveMelody/OctoPus";

#[derive(Deserialize)]
#[serde(rename_all = "snake_case")]
pub(crate) enum HelpDestination {
    Manual,
    Issues,
    Requests,
    Home,
    Releases,
}

pub(crate) fn project_url(destination: &HelpDestination) -> Option<String> {
    Some(match destination {
        HelpDestination::Manual => return None,
        HelpDestination::Issues => format!("{PROJECT}/issues"),
        HelpDestination::Requests => format!("{PROJECT}/pulls"),
        HelpDestination::Home => PROJECT.into(),
        HelpDestination::Releases => format!("{PROJECT}/releases"),
    })
}

#[cfg(debug_assertions)]
fn manual_path(_app: &AppHandle) -> Result<PathBuf, String> {
    Ok(PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../docs/user-manual.html"))
}

#[cfg(not(debug_assertions))]
fn manual_path(app: &AppHandle) -> Result<PathBuf, String> {
    app.path()
        .resolve("docs/user-manual.html", BaseDirectory::Resource)
        .map_err(|error| format!("could not locate user manual: {error}"))
}

pub(crate) fn manual_url(path: PathBuf, language: &str) -> Result<String, String> {
    let path = path
        .canonicalize()
        .map_err(|error| format!("user manual is unavailable: {error}"))?;
    if !path.is_file() {
        return Err("user manual is not a file".into());
    }
    let mut url = reqwest::Url::from_file_path(path).map_err(|()| "invalid user manual path")?;
    url.set_fragment(Some(if language == "zh-CN" { "zh-CN" } else { "en" }));
    Ok(url.to_string())
}

#[tauri::command]
pub(crate) fn open_help_destination(
    app: AppHandle,
    destination: HelpDestination,
    language: String,
) -> Result<(), String> {
    let url = match project_url(&destination) {
        Some(url) => url,
        None => manual_url(manual_path(&app)?, &language)?,
    };
    app.opener()
        .open_url(url, None::<&str>)
        .map_err(|error| format!("could not open browser: {error}"))
}

#[derive(Serialize)]
pub(crate) struct UpdateStatus {
    pub(crate) status: &'static str,
    pub(crate) current_version: String,
    pub(crate) latest_version: Option<String>,
}

#[derive(Deserialize)]
struct Release {
    tag_name: String,
    draft: bool,
    prerelease: bool,
}

pub(crate) fn release_status(bytes: &[u8], current: &str) -> Result<UpdateStatus, String> {
    let release: Release = serde_json::from_slice(bytes).map_err(|_| "invalid release response")?;
    if release.draft || release.prerelease || release.tag_name.len() > 128 {
        return Err("latest release response is not a stable release".into());
    }
    let version = semver::Version::parse(
        release
            .tag_name
            .strip_prefix('v')
            .unwrap_or(&release.tag_name),
    );
    let installed = semver::Version::parse(current).map_err(|_| "invalid installed version")?;
    let status = match version {
        Ok(latest) if latest > installed => "available",
        Ok(_) => "up_to_date",
        Err(_) => "unknown_version",
    };
    Ok(UpdateStatus {
        status,
        current_version: current.into(),
        latest_version: Some(release.tag_name),
    })
}

#[tauri::command]
pub(crate) async fn check_for_update(app: AppHandle) -> Result<UpdateStatus, String> {
    let current = app.package_info().version.to_string();
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(10))
        .redirect(reqwest::redirect::Policy::none())
        .user_agent(format!("OctoPus/{current}"))
        .build()
        .map_err(|error| format!("could not start update check: {error}"))?;
    let mut response = client
        .get("https://api.github.com/repos/OctaveMelody/OctoPus/releases/latest")
        .header("Accept", "application/vnd.github+json")
        .send()
        .await
        .map_err(|error| format!("update check failed: {error}"))?;
    if response.status() == reqwest::StatusCode::NOT_FOUND {
        return Ok(UpdateStatus {
            status: "unavailable",
            current_version: current,
            latest_version: None,
        });
    }
    if !response.status().is_success() {
        return Err(format!(
            "update server returned HTTP {}",
            response.status().as_u16()
        ));
    }
    let mut bytes = Vec::new();
    while let Some(chunk) = response
        .chunk()
        .await
        .map_err(|error| format!("could not read release: {error}"))?
    {
        if bytes.len() + chunk.len() > 65536 {
            return Err("release response is too large".into());
        }
        bytes.extend_from_slice(&chunk);
    }
    release_status(&bytes, &current)
}
