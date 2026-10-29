use serde::Deserialize;
use tauri::AppHandle;
use tauri::WebviewWindow;
use tauri_plugin_dialog::DialogExt;
use tauri_plugin_opener::OpenerExt;

use super::save_dialogs::{approved_save_path, confirm_replacements};

const PROJECT: &str = "https://github.com/OctaveMelody/OctoPus";
#[path = "help/manual.rs"]
mod manual;
#[path = "help/updates.rs"]
mod updates;

#[cfg(all(test, target_os = "linux"))]
#[allow(unused_imports)]
pub(crate) use manual::validated_appimage_docs_root;
#[cfg(test)]
#[allow(unused_imports)]
pub(crate) use manual::{
    copy_manual_docs, copy_manual_pdf, find_matching_manual_docs, manual_docs_match,
    manual_html_path_from_root, manual_pdf_filename, manual_staging_base, stage_manual_docs,
};
pub(crate) use updates::UpdateStatus;
#[cfg(test)]
#[allow(unused_imports)]
pub(crate) use updates::{release_status, retry_cooldown, UpdateCheckCache, UpdateCheckOutcome};

#[derive(Deserialize)]
#[serde(rename_all = "snake_case")]
pub(crate) enum HelpDestination {
    Manual,
    Issues,
    Requests,
    Home,
    Releases,
    #[serde(alias = "windows-fonts")]
    WindowsFonts,
    #[serde(alias = "macos-fonts")]
    MacosFonts,
}

pub(crate) fn project_url(destination: &HelpDestination) -> Option<String> {
    Some(match destination {
        HelpDestination::Manual => return None,
        HelpDestination::Issues => format!("{PROJECT}/issues"),
        HelpDestination::Requests => format!("{PROJECT}/pulls"),
        HelpDestination::Home => PROJECT.into(),
        HelpDestination::Releases => format!("{PROJECT}/releases"),
        HelpDestination::WindowsFonts => {
            "https://learn.microsoft.com/en-us/windows/deployment/windows-missing-fonts".into()
        }
        HelpDestination::MacosFonts => {
            "https://support.apple.com/en-gb/guide/font-book/fntbk1000/mac".into()
        }
    })
}

#[tauri::command]
pub(crate) async fn save_user_manual_pdf(
    app: AppHandle,
    window: WebviewWindow,
    language: String,
) -> Result<(), String> {
    let source = manual::manual_pdf_path(&app, &language)?;
    let filename = manual::manual_pdf_filename(&language).to_owned();
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
        manual::copy_manual_pdf(&source, &destination, &existing)
    })
    .await
    .map_err(|error| format!("user manual save dialog failed: {error}"))?
}

fn open_manual(app: &AppHandle, language: &str) -> Result<(), String> {
    let path = manual::manual_html_path(app, language)?;
    app.opener()
        .open_path(path.to_string_lossy().into_owned(), None::<&str>)
        .map_err(|error| format!("could not open user manual: {error}"))
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
            HelpDestination::WindowsFonts,
            HelpDestination::MacosFonts,
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
        assert_eq!(
            project_url(&HelpDestination::WindowsFonts).as_deref(),
            Some("https://learn.microsoft.com/en-us/windows/deployment/windows-missing-fonts"),
        );
        assert_eq!(
            project_url(&HelpDestination::MacosFonts).as_deref(),
            Some("https://support.apple.com/en-gb/guide/font-book/fntbk1000/mac"),
        );
        assert!(project_url(&HelpDestination::Manual).is_none());
    }
}

#[tauri::command]
pub(crate) async fn check_for_update(app: AppHandle) -> Result<UpdateStatus, String> {
    let current = app.package_info().version.to_string();
    updates::check(&current).await
}
