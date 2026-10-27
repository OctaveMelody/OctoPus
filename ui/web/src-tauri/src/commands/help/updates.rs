use serde::{Deserialize, Serialize};
use std::future::Future;
use std::sync::OnceLock;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};
use tauri::async_runtime::Mutex;

const UPDATE_CACHE_TTL: Duration = Duration::from_secs(5 * 60);
const UPDATE_RETRY_COOLDOWN: Duration = Duration::from_secs(60);
const MAX_UPDATE_RETRY_COOLDOWN: Duration = Duration::from_secs(60 * 60);

static UPDATE_CHECK_CACHE: OnceLock<UpdateCheckCache> = OnceLock::new();

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

pub(super) async fn check(current: &str) -> Result<UpdateStatus, String> {
    UPDATE_CHECK_CACHE
        .get_or_init(UpdateCheckCache::default)
        .check(current, Instant::now, || fetch_update(current))
        .await
}
