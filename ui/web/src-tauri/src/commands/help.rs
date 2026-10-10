use jps_document_io::file_exports::{publish_export_pages, ExportFormat};
use serde::{Deserialize, Serialize};
use std::fs;
use std::future::Future;
use std::path::Path;
use std::path::PathBuf;
use std::sync::OnceLock;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};
use tauri::async_runtime::Mutex;
#[cfg(not(debug_assertions))]
use tauri::path::BaseDirectory;
use tauri::AppHandle;
use tauri::WebviewWindow;
use tauri_plugin_dialog::DialogExt;
use tauri_plugin_opener::OpenerExt;

use super::save_dialogs::{approved_save_path, confirm_replacements};

const PROJECT: &str = "https://github.com/OctaveMelody/OctoPus";
const UPDATE_CACHE_TTL: Duration = Duration::from_secs(5 * 60);
const UPDATE_RETRY_COOLDOWN: Duration = Duration::from_secs(60);
const MAX_UPDATE_RETRY_COOLDOWN: Duration = Duration::from_secs(60 * 60);

static UPDATE_CHECK_CACHE: OnceLock<UpdateCheckCache> = OnceLock::new();

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

fn manual_filename(language: &str) -> &'static str {
    if language == "zh-CN" {
        "zh-CN.html"
    } else {
        "en.html"
    }
}

fn manual_pdf_filename(language: &str) -> &'static str {
    if language == "zh-CN" {
        "OctoPus-User-Manual-zh-CN.pdf"
    } else {
        "OctoPus-User-Manual-en.pdf"
    }
}

fn manual_pdf_path(_app: &AppHandle, language: &str) -> Result<PathBuf, String> {
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

#[tauri::command]
pub(crate) async fn save_user_manual_pdf(
    app: AppHandle,
    window: WebviewWindow,
    language: String,
) -> Result<(), String> {
    let source = manual_pdf_path(&app, &language)?;
    let filename = manual_pdf_filename(&language).to_owned();
    tauri::async_runtime::spawn_blocking(move || {
        let selected = window
            .dialog()
            .file()
            .set_parent(&window)
            .add_filter("PDF document", &["pdf"])
            .set_file_name(filename)
            .blocking_save_file();
        let Some(selected) = selected else {
            return Ok(());
        };
        let selected = selected
            .into_path()
            .map_err(|_| "save dialog did not return a local path".to_owned())?;
        let Some((destination, replace_existing)) =
            approved_save_path(&selected, "pdf", |paths| {
                confirm_replacements(&window, paths)
            })?
        else {
            return Ok(());
        };
        let existing = if replace_existing {
            vec![destination.clone()]
        } else {
            Vec::new()
        };
        copy_manual_pdf(&source, &destination, &existing)
    })
    .await
    .map_err(|error| format!("user manual save dialog failed: {error}"))?
}

fn open_manual(app: &AppHandle, language: &str) -> Result<(), String> {
    let path = manual_html_path(app, language)?;
    app.opener()
        .open_path(path.to_string_lossy().into_owned(), None::<&str>)
        .map_err(|error| format!("could not open user manual: {error}"))
}

fn manual_html_path(_app: &AppHandle, language: &str) -> Result<PathBuf, String> {
    let filename = manual_filename(language);
    #[cfg(debug_assertions)]
    let path = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../../../build/pdfjs-assets/docs/user-manual")
        .join(filename);
    #[cfg(not(debug_assertions))]
    let path = _app
        .path()
        .resolve(
            crate::resource_relative(&format!("docs/user-manual/{filename}")),
            BaseDirectory::Resource,
        )
        .map_err(|error| format!("could not locate bundled user manual: {error}"))?;
    if !path.is_file() {
        return Err(format!(
            "bundled user manual is missing: {}",
            path.display()
        ));
    }
    Ok(path)
}

#[tauri::command]
pub(crate) fn open_help_destination(
    app: AppHandle,
    destination: HelpDestination,
    language: String,
) -> Result<(), String> {
    match project_url(&destination) {
        Some(url) => app
            .opener()
            .open_url(url, None::<&str>)
            .map_err(|error| format!("could not open browser: {error}")),
        None => open_manual(&app, &language),
    }
}

fn is_internal_app_origin(url: &reqwest::Url) -> bool {
    matches!(
        (url.scheme(), url.host_str()),
        ("tauri", Some("localhost"))
            | ("http", Some("tauri.localhost"))
            | ("https", Some("tauri.localhost"))
    ) || (cfg!(debug_assertions)
        && url.scheme() == "http"
        && url.host_str() == Some("127.0.0.1")
        && url.port() == Some(5173))
}

fn is_external_web_url(raw_url: &str) -> bool {
    let Ok(url) = reqwest::Url::parse(raw_url) else {
        return false;
    };
    matches!(url.scheme(), "http" | "https")
        && url.host_str().is_some()
        && !is_internal_app_origin(&url)
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
struct ManualNavigationDecision {
    allow_in_app: bool,
    open_in_default_browser: bool,
}

fn app_navigation_decision(raw_url: &str) -> ManualNavigationDecision {
    let Ok(url) = reqwest::Url::parse(raw_url) else {
        return ManualNavigationDecision {
            allow_in_app: false,
            open_in_default_browser: false,
        };
    };
    if is_internal_app_origin(&url) {
        ManualNavigationDecision {
            allow_in_app: true,
            open_in_default_browser: false,
        }
    } else if is_external_web_url(raw_url) {
        ManualNavigationDecision {
            allow_in_app: false,
            open_in_default_browser: true,
        }
    } else {
        ManualNavigationDecision {
            allow_in_app: false,
            open_in_default_browser: false,
        }
    }
}

pub(crate) fn handle_app_navigation(app: &AppHandle, raw_url: &str) -> bool {
    let decision = app_navigation_decision(raw_url);
    if decision.open_in_default_browser {
        open_external_web_url(app, raw_url);
    }
    decision.allow_in_app
}

pub(crate) fn open_app_new_window(app: &AppHandle, raw_url: &str) {
    if app_navigation_decision(raw_url).open_in_default_browser {
        open_external_web_url(app, raw_url);
    }
}

fn open_external_web_url(app: &AppHandle, url: &str) {
    if is_external_web_url(url) {
        let _ = app.opener().open_url(url.to_owned(), None::<&str>);
    }
}

#[cfg(test)]
mod tests {
    use super::{
        app_navigation_decision, is_external_web_url, manual_pdf_filename, project_url,
        HelpDestination, ManualNavigationDecision,
    };
    #[test]
    fn manual_pdf_filename_uses_the_selected_language() {
        assert_eq!(manual_pdf_filename("en"), "OctoPus-User-Manual-en.pdf");
        assert_eq!(
            manual_pdf_filename("zh-CN"),
            "OctoPus-User-Manual-zh-CN.pdf"
        );
    }

    #[test]
    fn manual_links_open_external_web_urls_instead_of_navigating_the_webview() {
        assert!(is_external_web_url("https://example.com/"));
        assert!(is_external_web_url("http://zhipu.lezhi99.com"));
        assert!(!is_external_web_url("javascript:alert(1)"));
        assert!(!is_external_web_url("file:///tmp/example.html"));
        assert!(!is_external_web_url(
            "http://tauri.localhost/docs/user-manual/en.html"
        ));
    }

    #[test]
    fn app_navigation_keeps_app_origins_and_routes_only_external_web_links_to_default_browser() {
        for url in [
            "tauri://localhost/",
            "http://tauri.localhost/",
            "https://tauri.localhost/",
        ] {
            assert_eq!(
                app_navigation_decision(url),
                ManualNavigationDecision {
                    allow_in_app: true,
                    open_in_default_browser: false,
                }
            );
        }
        for url in ["https://example.com/", "http://zhipu.lezhi99.com"] {
            assert_eq!(
                app_navigation_decision(url),
                ManualNavigationDecision {
                    allow_in_app: false,
                    open_in_default_browser: true,
                }
            );
        }
        for url in [
            "javascript:alert(1)",
            "file:///tmp/example.html",
            "mailto:help@example.com",
        ] {
            assert_eq!(
                app_navigation_decision(url),
                ManualNavigationDecision {
                    allow_in_app: false,
                    open_in_default_browser: false,
                }
            );
        }
    }

    #[test]
    fn help_destinations_are_web_urls_routed_to_the_default_browser() {
        let destinations = [
            HelpDestination::Issues,
            HelpDestination::Requests,
            HelpDestination::Home,
            HelpDestination::Releases,
        ];
        for destination in destinations {
            let url = project_url(&destination).expect("external Help destination has a URL");
            assert!(is_external_web_url(&url));
            assert_eq!(
                app_navigation_decision(&url),
                ManualNavigationDecision {
                    allow_in_app: false,
                    open_in_default_browser: true,
                }
            );
        }
        assert!(project_url(&HelpDestination::Manual).is_none());
    }
}

#[derive(Clone, Debug, Serialize)]
pub(crate) struct UpdateStatus {
    pub(crate) status: &'static str,
    pub(crate) current_version: String,
    pub(crate) latest_version: Option<String>,
}

pub(crate) struct UpdateCheckOutcome {
    pub(crate) result: Result<UpdateStatus, String>,
    pub(crate) ttl: Duration,
}

impl UpdateCheckOutcome {
    pub(crate) fn new(result: Result<UpdateStatus, String>) -> Self {
        let ttl = if result.is_ok() {
            UPDATE_CACHE_TTL
        } else {
            UPDATE_RETRY_COOLDOWN
        };
        Self { result, ttl }
    }
}

struct CachedUpdateCheck {
    current_version: String,
    expires_at: Instant,
    result: Result<UpdateStatus, String>,
}

#[derive(Default)]
pub(crate) struct UpdateCheckCache {
    entry: Mutex<Option<CachedUpdateCheck>>,
}

impl UpdateCheckCache {
    pub(crate) async fn check<F, Fut, Clock>(
        &self,
        current: &str,
        now: Clock,
        fetch: F,
    ) -> Result<UpdateStatus, String>
    where
        F: FnOnce() -> Fut,
        Fut: Future<Output = UpdateCheckOutcome>,
        Clock: Fn() -> Instant,
    {
        // Keep the lock while fetching so concurrent commands share one completed outcome.
        let mut entry = self.entry.lock().await;
        if let Some(cached) = entry.as_ref() {
            if cached.current_version == current && now() < cached.expires_at {
                return cached.result.clone();
            }
        }
        let outcome = fetch().await;
        *entry = Some(CachedUpdateCheck {
            current_version: current.into(),
            expires_at: now() + outcome.ttl.min(MAX_UPDATE_RETRY_COOLDOWN),
            result: outcome.result.clone(),
        });
        outcome.result
    }
}

pub(crate) fn retry_cooldown(
    status: reqwest::StatusCode,
    headers: &reqwest::header::HeaderMap,
    now: SystemTime,
) -> Duration {
    // GitHub documents Retry-After as seconds and primary reset as Unix seconds.
    let retry_after = headers
        .get(reqwest::header::RETRY_AFTER)
        .and_then(|value| value.to_str().ok())
        .and_then(|value| value.parse::<u64>().ok())
        .unwrap_or(0);
    let reset = if matches!(status.as_u16(), 403 | 429)
        && headers
            .get("x-ratelimit-remaining")
            .is_some_and(|value| value == "0")
    {
        headers
            .get("x-ratelimit-reset")
            .and_then(|value| value.to_str().ok())
            .and_then(|value| value.parse::<u64>().ok())
            .map(|reset| {
                reset.saturating_sub(now.duration_since(UNIX_EPOCH).unwrap_or_default().as_secs())
            })
            .unwrap_or(0)
    } else {
        0
    };
    Duration::from_secs(retry_after.max(reset))
        .max(UPDATE_RETRY_COOLDOWN)
        .min(MAX_UPDATE_RETRY_COOLDOWN)
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
    UPDATE_CHECK_CACHE
        .get_or_init(UpdateCheckCache::default)
        .check(&current, Instant::now, || fetch_update(&current))
        .await
}

async fn fetch_update(current: &str) -> UpdateCheckOutcome {
    let mut retry_ttl = None;
    let result = fetch_release(current, &mut retry_ttl).await;
    let mut outcome = UpdateCheckOutcome::new(result);
    if let Some(ttl) = retry_ttl {
        outcome.ttl = ttl;
    }
    outcome
}

async fn fetch_release(
    current: &str,
    retry_ttl: &mut Option<Duration>,
) -> Result<UpdateStatus, String> {
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
            current_version: current.into(),
            latest_version: None,
        });
    }
    if !response.status().is_success() {
        *retry_ttl = Some(retry_cooldown(
            response.status(),
            response.headers(),
            SystemTime::now(),
        ));
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
    release_status(&bytes, current)
}
