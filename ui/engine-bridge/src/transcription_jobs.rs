//! Correlate cancellation before or after native transcription registration.
use std::collections::VecDeque;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

const MAX_PENDING_CANCELLATIONS: usize = 64;
const PENDING_CANCELLATION_TTL: Duration = Duration::from_secs(900);

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct JobKey {
    pub id: String,
    pub document_id: String,
    pub revision: u64,
}
impl JobKey {
    fn validate(&self) -> Result<(), String> {
        if [&self.id, &self.document_id].iter().any(|value| {
            value.is_empty() || value.len() > 128 || value.chars().any(char::is_control)
        }) || self.revision > (1_u64 << 53) - 1
        {
            return Err("invalid transcription job identity".into());
        }
        Ok(())
    }
}
struct ActiveJob {
    key: JobKey,
    cancelled: Arc<AtomicBool>,
}
#[derive(Default)]
struct JobsState {
    active: Option<ActiveJob>,
    pending: VecDeque<(JobKey, Instant)>,
}
#[derive(Default)]
pub struct TranscriptionJobs(Mutex<JobsState>);
impl TranscriptionJobs {
    pub fn register(&self, key: JobKey) -> Result<Arc<AtomicBool>, String> {
        key.validate()?;
        let mut state = self.0.lock().map_err(|_| "transcription lock poisoned")?;
        prune(&mut state.pending, Instant::now());
        if let Some(index) = state
            .pending
            .iter()
            .position(|(pending, _)| pending == &key)
        {
            state.pending.remove(index);
            return Err("transcription cancelled".into());
        }
        if state.active.is_some() {
            return Err("a transcription is already running".into());
        }
        let cancelled = Arc::new(AtomicBool::new(false));
        state.active = Some(ActiveJob {
            key,
            cancelled: Arc::clone(&cancelled),
        });
        Ok(cancelled)
    }

    pub fn cancel(&self, key: JobKey) -> Result<bool, String> {
        key.validate()?;
        let mut state = self.0.lock().map_err(|_| "transcription lock poisoned")?;
        if let Some(job) = state.active.as_ref().filter(|job| job.key == key) {
            job.cancelled.store(true, Ordering::Release);
            return Ok(true);
        }
        let now = Instant::now();
        prune(&mut state.pending, now);
        // A cancellation that beats registration is remembered once, with bounded retention.
        state.pending.retain(|(pending, _)| pending != &key);
        if state.pending.len() == MAX_PENDING_CANCELLATIONS {
            state.pending.pop_front();
        }
        state.pending.push_back((key, now));
        Ok(false)
    }

    pub fn finish(&self, key: &JobKey, cancelled: &Arc<AtomicBool>) {
        if let Ok(mut state) = self.0.lock() {
            if state
                .active
                .as_ref()
                .is_some_and(|job| job.key == *key && Arc::ptr_eq(&job.cancelled, cancelled))
            {
                state.active.take();
            }
        }
    }
}
fn prune(pending: &mut VecDeque<(JobKey, Instant)>, now: Instant) {
    pending
        .retain(|(_, created)| now.saturating_duration_since(*created) < PENDING_CANCELLATION_TTL);
}
