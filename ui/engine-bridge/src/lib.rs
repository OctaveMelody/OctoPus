use serde::Deserialize;
use serde_json::{json, Value};
#[cfg(test)]
use std::ffi::OsString;
use std::io::{self, BufRead, BufReader, BufWriter, Write};
#[cfg(debug_assertions)]
use std::path::Path;
use std::path::PathBuf;
use std::process::{ChildStdin, ChildStdout, Command, Stdio};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{mpsc, Arc, Mutex};
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant};

mod process;
pub mod transcription_jobs;
use process::WorkerProcess;

const PROTOCOL_VERSION: &str = "1.7.0";
const MAX_REQUEST_BYTES: usize = 10 * 1024 * 1024;
const MAX_RESPONSE_BYTES: usize = 64 * 1024 * 1024;
const REQUEST_TIMEOUT: Duration = Duration::from_secs(60);
static NEXT_REQUEST_ID: AtomicU64 = AtomicU64::new(1);

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct RenderArgs {
    pub document_id: String,
    pub document_revision: u64,
    pub name: String,
    pub code: String,
    pub custom_code: String,
    pub page_config: Value,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct RenderPageArgs {
    pub document_id: String,
    pub document_revision: u64,
    pub name: String,
    pub code: String,
    pub custom_code: String,
    pub page_config: Value,
    pub page_index: u64,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct LoadDocumentArgs {
    pub document_id: String,
    pub document_revision: u64,
    pub name: String,
    pub text: String,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SerializeDocumentArgs {
    pub document_id: String,
    pub document_revision: u64,
    pub name: String,
    pub code: String,
    pub wrapper_fields: Value,
    pub page_config: Value,
    pub page_config_changed: bool,
    pub json_wrapped: bool,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct TranscribeArgs {
    pub document_id: String,
    pub document_revision: u64,
    pub path: String,
}

pub struct EngineSupervisor {
    process: Option<EngineProcess>,
    launch: EngineLaunch,
    request_timeout: Duration,
    shutdown: Arc<AtomicBool>,
}

enum EngineLaunch {
    #[cfg(debug_assertions)]
    Development,
    Packaged(PathBuf),
    #[cfg(not(debug_assertions))]
    Unconfigured,
    #[cfg(test)]
    Command {
        program: OsString,
        args: Vec<OsString>,
    },
}

impl EngineLaunch {
    fn command(&self) -> Result<Command, String> {
        match self {
            #[cfg(debug_assertions)]
            Self::Development => {
                let root = Path::new(env!("CARGO_MANIFEST_DIR"))
                    .ancestors()
                    .nth(2)
                    .filter(|path| path.join("pyproject.toml").is_file())
                    .ok_or("could not locate the repository Python project")?;
                let environment = std::env::var_os("UV_PROJECT_ENVIRONMENT")
                    .map(PathBuf::from)
                    .unwrap_or_else(|| root.join(".venv"));
                let environment = if environment.is_absolute() {
                    environment
                } else {
                    root.join(environment)
                };
                let interpreter = environment.join(if cfg!(windows) {
                    "Scripts/python.exe"
                } else {
                    "bin/python"
                });
                if !interpreter.is_file() {
                    return Err("development Python environment missing; run `uv sync`".into());
                }
                let mut command = Command::new(interpreter);
                command.args(["-m", "ui.engine"]).current_dir(root);
                Ok(command)
            }
            Self::Packaged(executable) => {
                if !executable.is_absolute() {
                    return Err("packaged Python engine path must be absolute".into());
                }
                if !executable.is_file() {
                    return Err("packaged Python engine executable is missing".into());
                }
                let mut command = Command::new(executable);
                if let Some(directory) = executable.parent() {
                    command.current_dir(directory);
                }
                Ok(command)
            }
            #[cfg(not(debug_assertions))]
            Self::Unconfigured => Err("packaged Python engine resource is not configured".into()),
            #[cfg(test)]
            Self::Command { program, args } => {
                let mut command = Command::new(program);
                command.args(args);
                Ok(command)
            }
        }
    }
}

struct EngineProcess {
    child: Arc<Mutex<WorkerProcess>>,
    sender: mpsc::SyncSender<WorkerCommand>,
    worker: Option<JoinHandle<()>>,
    capabilities: Value,
}

type ProgressHandler = Box<dyn Fn(Value) + Send>;

struct WorkerMessage {
    request: Vec<u8>,
    request_id: String,
    document_id: String,
    revision: u64,
    reply: mpsc::SyncSender<Result<Value, String>>,
    progress: Option<ProgressHandler>,
}

enum WorkerCommand {
    Request(WorkerMessage),
    Stop,
}

#[cfg(debug_assertions)]
impl Default for EngineSupervisor {
    fn default() -> Self {
        Self {
            process: None,
            launch: EngineLaunch::Development,
            request_timeout: REQUEST_TIMEOUT,
            shutdown: Arc::default(),
        }
    }
}

#[cfg(not(debug_assertions))]
impl Default for EngineSupervisor {
    fn default() -> Self {
        Self {
            process: None,
            launch: EngineLaunch::Unconfigured,
            request_timeout: REQUEST_TIMEOUT,
            shutdown: Arc::default(),
        }
    }
}

impl EngineSupervisor {
    pub fn packaged(executable: PathBuf) -> Self {
        Self {
            process: None,
            launch: EngineLaunch::Packaged(executable),
            request_timeout: REQUEST_TIMEOUT,
            shutdown: Arc::default(),
        }
    }

    #[cfg(test)]
    fn test_command(program: impl Into<OsString>, args: &[&str], timeout: Duration) -> Self {
        Self {
            process: None,
            launch: EngineLaunch::Command {
                program: program.into(),
                args: args.iter().map(OsString::from).collect(),
            },
            request_timeout: timeout,
            shutdown: Arc::default(),
        }
    }

    pub fn capabilities(&mut self) -> Result<Value, String> {
        if self.shutdown.load(Ordering::Acquire) {
            return Err("engine shut down".into());
        }
        if self.process.is_none() {
            self.process = Some(EngineProcess::spawn(
                &self.launch,
                self.request_timeout,
                None,
                &self.shutdown,
            )?);
        }
        Ok(self
            .process
            .as_ref()
            .expect("engine was spawned")
            .capabilities
            .clone())
    }

    pub fn shutdown_signal(&self) -> Arc<AtomicBool> {
        Arc::clone(&self.shutdown)
    }

    pub fn shutdown(&mut self) {
        self.shutdown.store(true, Ordering::Release);
        self.process.take();
    }

    pub fn render(&mut self, args: RenderArgs) -> Result<Value, String> {
        self.render_with_operation(args, "render")
    }

    pub fn parse(&mut self, args: RenderArgs) -> Result<Value, String> {
        self.render_with_operation(args, "parse")
    }

    pub fn export_svg(&mut self, args: RenderArgs) -> Result<Value, String> {
        self.render_with_operation(args, "export_svg")
    }

    fn render_with_operation(
        &mut self,
        args: RenderArgs,
        operation: &str,
    ) -> Result<Value, String> {
        self.call(
            args.document_id,
            args.document_revision,
            operation,
            json!({
                "name": args.name,
                "code": args.code,
                "custom_code": args.custom_code,
                "page_config": args.page_config
            }),
        )
    }

    pub fn render_page(&mut self, args: RenderPageArgs) -> Result<Value, String> {
        if args.page_index > (1_u64 << 53) - 1 {
            return Err("page index exceeds the safe integer range".into());
        }
        self.call(
            args.document_id,
            args.document_revision,
            "render_page",
            json!({
                "name": args.name,
                "code": args.code,
                "custom_code": args.custom_code,
                "page_config": args.page_config,
                "page_index": args.page_index
            }),
        )
    }

    pub fn load_document(&mut self, args: LoadDocumentArgs) -> Result<Value, String> {
        self.call(
            args.document_id,
            args.document_revision,
            "load_document",
            json!({ "name": args.name, "text": args.text }),
        )
    }

    pub fn serialize_document(&mut self, args: SerializeDocumentArgs) -> Result<Value, String> {
        self.call(
            args.document_id,
            args.document_revision,
            "serialize_document",
            json!({
                "name": args.name,
                "code": args.code,
                "wrapper_fields": args.wrapper_fields,
                "page_config": args.page_config,
                "page_config_changed": args.page_config_changed,
                "json_wrapped": args.json_wrapped
            }),
        )
    }

    pub fn transcribe(&mut self, args: TranscribeArgs) -> Result<Value, String> {
        self.transcribe_with_progress(args, Arc::new(AtomicBool::new(false)), |_| {})
    }

    pub fn transcribe_with_progress(
        &mut self,
        args: TranscribeArgs,
        cancelled: Arc<AtomicBool>,
        progress: impl Fn(Value) + Send + 'static,
    ) -> Result<Value, String> {
        self.call_controlled(
            args.document_id,
            args.document_revision,
            "transcribe",
            json!({ "path": args.path }),
            Duration::from_secs(900),
            Some(cancelled),
            Some(Box::new(progress)),
        )
    }

    fn call(
        &mut self,
        document_id: String,
        revision: u64,
        operation: &str,
        payload: Value,
    ) -> Result<Value, String> {
        self.call_with_timeout(
            document_id,
            revision,
            operation,
            payload,
            self.request_timeout,
        )
    }

    fn call_with_timeout(
        &mut self,
        document_id: String,
        revision: u64,
        operation: &str,
        payload: Value,
        timeout: Duration,
    ) -> Result<Value, String> {
        self.call_controlled(
            document_id,
            revision,
            operation,
            payload,
            timeout,
            None,
            None,
        )
    }

    #[allow(clippy::too_many_arguments)]
    fn call_controlled(
        &mut self,
        document_id: String,
        revision: u64,
        operation: &str,
        payload: Value,
        timeout: Duration,
        cancelled: Option<Arc<AtomicBool>>,
        progress: Option<ProgressHandler>,
    ) -> Result<Value, String> {
        if self.shutdown.load(Ordering::Acquire) {
            return Err("engine shut down".into());
        }
        if cancelled
            .as_deref()
            .is_some_and(|flag| flag.load(Ordering::Acquire))
        {
            return Err("transcription cancelled".into());
        }
        if document_id.is_empty() || document_id.len() > 128 {
            return Err("document ID must be 1–128 bytes".into());
        }
        if revision > (1_u64 << 53) - 1 {
            return Err("document revision exceeds the safe integer range".into());
        }
        let request_id = NEXT_REQUEST_ID.fetch_add(1, Ordering::Relaxed).to_string();
        let request = json!({
            "protocol_version": PROTOCOL_VERSION,
            "request_id": request_id,
            "document_id": document_id,
            "document_revision": revision,
            "operation": operation,
            "payload": payload
        });
        let request = serde_json::to_vec(&request).map_err(|error| error.to_string())?;
        if request.len() + 1 > MAX_REQUEST_BYTES {
            return Err("request exceeds the protocol byte limit".into());
        }
        if self.process.is_none() {
            self.process = Some(EngineProcess::spawn(
                &self.launch,
                self.request_timeout,
                cancelled.as_deref(),
                &self.shutdown,
            )?);
        }
        let process = self.process.as_mut().expect("engine was spawned");
        let result = process.request(
            request,
            request_id,
            document_id,
            revision,
            timeout,
            cancelled.as_deref(),
            progress,
            &self.shutdown,
        );
        if result.is_err() {
            self.process.take();
        }
        result
    }
}

impl EngineProcess {
    fn spawn(
        launch: &EngineLaunch,
        request_timeout: Duration,
        cancelled: Option<&AtomicBool>,
        shutdown: &AtomicBool,
    ) -> Result<Self, String> {
        let mut command = launch.command()?;
        command
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit());
        let mut child = WorkerProcess::spawn(command)
            .map_err(|error| format!("could not start Python engine: {error}"))?;
        let Some(stdin) = child.child.stdin.take() else {
            return Err("Python engine stdin unavailable".into());
        };
        let Some(stdout) = child.child.stdout.take() else {
            return Err("Python engine stdout unavailable".into());
        };
        let child = Arc::new(Mutex::new(child));
        let (sender, receiver) = mpsc::sync_channel(1);
        let (startup_sender, startup_receiver) = mpsc::sync_channel(1);
        let worker_child = Arc::clone(&child);
        let worker = match thread::Builder::new()
            .name("jps-render-engine".into())
            .spawn(move || engine_worker(stdin, stdout, receiver, startup_sender, worker_child))
        {
            Ok(worker) => worker,
            Err(error) => {
                stop_child(&child);
                return Err(format!("could not start render supervisor: {error}"));
            }
        };
        let capabilities =
            match receive_controlled(&startup_receiver, request_timeout, cancelled, shutdown) {
                Ok(Ok(capabilities)) => capabilities,
                Ok(Err(error)) => {
                    stop_child(&child);
                    let _ = worker.join();
                    return Err(error);
                }
                Err(error) => {
                    stop_child(&child);
                    let _ = worker.join();
                    return Err(format!(
                        "Python engine handshake timed out or stopped: {error}"
                    ));
                }
            };
        Ok(Self {
            child,
            sender,
            worker: Some(worker),
            capabilities,
        })
    }

    #[allow(clippy::too_many_arguments)]
    fn request(
        &mut self,
        request: Vec<u8>,
        request_id: String,
        document_id: String,
        revision: u64,
        timeout: Duration,
        cancelled: Option<&AtomicBool>,
        progress: Option<ProgressHandler>,
        shutdown: &AtomicBool,
    ) -> Result<Value, String> {
        let (reply, receiver) = mpsc::sync_channel(1);
        self.sender
            .send(WorkerCommand::Request(WorkerMessage {
                request,
                request_id,
                document_id,
                revision,
                reply,
                progress,
            }))
            .map_err(|_| "Python worker stopped".to_owned())?;
        match receive_controlled(&receiver, timeout, cancelled, shutdown) {
            Ok(result) => result,
            Err(error) => {
                self.terminate();
                Err(format!("Python request timed out or stopped: {error}"))
            }
        }
    }

    fn terminate(&mut self) {
        let _ = self.sender.try_send(WorkerCommand::Stop);
        stop_child(&self.child);
        if let Some(worker) = self.worker.take() {
            let _ = worker.join();
        }
    }
}

impl Drop for EngineProcess {
    fn drop(&mut self) {
        self.terminate();
    }
}

fn receive_controlled<T>(
    receiver: &mpsc::Receiver<T>,
    timeout: Duration,
    cancelled: Option<&AtomicBool>,
    shutdown: &AtomicBool,
) -> Result<T, String> {
    let deadline = Instant::now() + timeout;
    loop {
        if shutdown.load(Ordering::Acquire) {
            return Err("engine shut down".into());
        }
        if cancelled.is_some_and(|flag| flag.load(Ordering::Acquire)) {
            return Err("transcription cancelled".into());
        }
        let remaining = deadline.saturating_duration_since(Instant::now());
        if remaining.is_zero() {
            return Err("request timeout".into());
        }
        match receiver.recv_timeout(remaining.min(Duration::from_millis(50))) {
            Ok(value) => {
                if cancelled.is_some_and(|flag| flag.load(Ordering::Acquire)) {
                    return Err("transcription cancelled".into());
                }
                return Ok(value);
            }
            Err(mpsc::RecvTimeoutError::Timeout) => {}
            Err(error) => return Err(error.to_string()),
        }
    }
}

fn engine_worker(
    stdin: ChildStdin,
    stdout: ChildStdout,
    receiver: mpsc::Receiver<WorkerCommand>,
    startup: mpsc::SyncSender<Result<Value, String>>,
    child: Arc<Mutex<WorkerProcess>>,
) {
    let mut writer = BufWriter::new(stdin);
    let mut reader = BufReader::new(stdout);
    let handshake = json!({
        "protocol_version": PROTOCOL_VERSION,
        "request_id": "handshake-0",
        "document_id": "desktop",
        "document_revision": 0,
        "operation": "handshake",
        "payload": {}
    });
    let handshake = (|| {
        write_frame(&mut writer, &handshake)?;
        let response = read_response(&mut reader)?;
        let generation = validate_response(&response, "handshake-0", "desktop", 0, None, true)?;
        Ok((generation, response["result"].clone()))
    })();
    let (generation, capabilities) = match handshake {
        Ok(handshake) => handshake,
        Err(error) => {
            let _ = startup.send(Err(error));
            stop_child(&child);
            return;
        }
    };
    if startup.send(Ok(capabilities.clone())).is_err() {
        stop_child(&child);
        return;
    }
    while let Ok(command) = receiver.recv() {
        let WorkerCommand::Request(message) = command else {
            break;
        };
        let response = (|| {
            writer.write_all(&message.request).map_err(io_message)?;
            writer.write_all(b"\n").map_err(io_message)?;
            writer.flush().map_err(io_message)?;
            let mut completed = 0;
            let mut total = None;
            let mut compiling = false;
            let mut progress_frames = 0_u64;
            loop {
                let value = read_response(&mut reader)?;
                if value["status"] == "progress" {
                    let handler = message
                        .progress
                        .as_ref()
                        .ok_or("unexpected progress frame")?;
                    // Validate the same correlation fields as the final response.
                    let mut envelope = value.clone();
                    envelope["status"] = json!("ok");
                    validate_response(
                        &envelope,
                        &message.request_id,
                        &message.document_id,
                        message.revision,
                        Some(&generation),
                        false,
                    )?;
                    let page = value["result"]["completed"]
                        .as_u64()
                        .ok_or("invalid progress count")?;
                    let count = value["result"]["total"]
                        .as_u64()
                        .ok_or("invalid progress total")?;
                    progress_frames += 1;
                    let stage = value["result"]["stage"].as_str();
                    if !(1..=200).contains(&count)
                        || page > count
                        || page < completed
                        || total.is_some_and(|old| old != count)
                        || progress_frames > count * 2 + 2
                        || !matches!(stage, Some("recognizing" | "compiling"))
                        || (compiling && stage != Some("compiling"))
                        || (stage == Some("compiling") && page != count)
                    {
                        return Err("invalid transcription progress".into());
                    }
                    completed = page;
                    total = Some(count);
                    compiling |= stage == Some("compiling");
                    handler(value["result"].clone());
                    continue;
                }
                validate_response(
                    &value,
                    &message.request_id,
                    &message.document_id,
                    message.revision,
                    Some(&generation),
                    false,
                )?;
                if value["status"] == "ok"
                    && total
                        .is_some_and(|count| value["result"]["page_count"].as_u64() != Some(count))
                {
                    return Err("transcription result disagrees with progress page total".into());
                }
                return Ok(value);
            }
        })();
        let failed = response.is_err();
        let _ = message.reply.send(response);
        if failed {
            stop_child(&child);
            return;
        }
    }
}

fn write_frame(writer: &mut impl Write, request: &Value) -> Result<(), String> {
    let bytes = serde_json::to_vec(request).map_err(io_message)?;
    if bytes.len() + 1 > MAX_REQUEST_BYTES {
        return Err("handshake exceeds the protocol byte limit".into());
    }
    writer.write_all(&bytes).map_err(io_message)?;
    writer.write_all(b"\n").map_err(io_message)?;
    writer.flush().map_err(io_message)
}

fn read_response(reader: &mut impl BufRead) -> Result<Value, String> {
    let line = read_bounded_line(reader, MAX_RESPONSE_BYTES).map_err(io_message)?;
    if line.is_empty() {
        return Err("Python engine closed its output".into());
    }
    serde_json::from_slice(&line).map_err(|error| format!("invalid engine JSON response: {error}"))
}

fn read_bounded_line(reader: &mut impl BufRead, limit: usize) -> io::Result<Vec<u8>> {
    let mut line = Vec::new();
    loop {
        let available = reader.fill_buf()?;
        if available.is_empty() {
            return Ok(line);
        }
        let length = available
            .iter()
            .position(|byte| *byte == b'\n')
            .map_or(available.len(), |index| index + 1);
        if line.len() + length > limit {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "Python response exceeds the protocol byte limit",
            ));
        }
        let complete = available.get(length - 1) == Some(&b'\n');
        line.extend_from_slice(&available[..length]);
        reader.consume(length);
        if complete {
            return Ok(line);
        }
    }
}

fn validate_response(
    response: &Value,
    request_id: &str,
    document_id: &str,
    revision: u64,
    expected_generation: Option<&str>,
    handshake: bool,
) -> Result<String, String> {
    let generation = response["engine_generation"]
        .as_str()
        .filter(|value| !value.is_empty() && value.len() <= 128)
        .ok_or("engine response has invalid generation")?;
    if response["protocol_version"] != PROTOCOL_VERSION
        || response["request_id"] != request_id
        || response["document_id"] != document_id
        || response["document_revision"].as_u64() != Some(revision)
        || !matches!(response["status"].as_str(), Some("ok" | "error"))
        || expected_generation.is_some_and(|expected| expected != generation)
    {
        return Err("engine response protocol, identity, status, or generation mismatch".into());
    }
    if response["status"] == "ok" {
        let result = response
            .get("result")
            .ok_or("successful response has no result")?;
        if handshake
            && (!result["operations"].as_array().is_some_and(|operations| {
                [
                    "handshake",
                    "load_document",
                    "render",
                    "parse",
                    "export_svg",
                    "render_page",
                    "serialize_document",
                    "transcribe",
                ]
                .iter()
                .all(|expected| operations.iter().any(|operation| operation == expected))
            }) || !result["custom_svg_display"].is_boolean()
                || !result["ocr"].is_boolean()
                || !result["png_export"].is_boolean())
        {
            return Err("engine handshake has invalid operations or capabilities".into());
        }
    } else if !response.get("error").is_some_and(Value::is_object) {
        return Err("failed response has no structured error".into());
    }
    Ok(generation.to_owned())
}

fn io_message(error: impl std::fmt::Display) -> String {
    error.to_string()
}

fn stop_child(child: &Arc<Mutex<WorkerProcess>>) {
    child
        .lock()
        .unwrap_or_else(|error| error.into_inner())
        .stop();
}

#[cfg(test)]
mod tests {
    use super::process::WorkerProcess;
    use super::{
        read_bounded_line, validate_response, EngineSupervisor, RenderArgs, TranscribeArgs,
    };
    use serde_json::json;
    use std::io::{BufReader, Cursor, ErrorKind};
    use std::sync::atomic::{AtomicBool, Ordering};
    use std::sync::{Arc, Mutex};
    use std::time::{Duration, Instant};

    const FAKE_ENGINE: &str = r#"
import json, os, subprocess, sys, time
mode = sys.argv[1]
descendant = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"]) if mode.startswith("child-") else None
mode = mode.removeprefix("child-")
if len(sys.argv) > 2:
    with open(sys.argv[2], "w") as output:
        json.dump([os.getpid(), descendant.pid if descendant else None], output)
operations = ["handshake", "load_document", "render", "parse", "export_svg", "render_page", "serialize_document", "transcribe"]
for line in sys.stdin:
    request = json.loads(line)
    operation = request["operation"]
    if mode == "hang-handshake" and operation == "handshake":
        time.sleep(30)
        continue
    if mode == "hang-request" and operation != "handshake":
        time.sleep(30)
        continue
    response = {
        "protocol_version": "wrong" if mode == "bad-version" else request["protocol_version"],
        "engine_generation": "fake-worker",
        "request_id": request["request_id"],
        "document_id": request["document_id"],
        "document_revision": request["document_revision"] + (1 if mode == "bad-response" and operation != "handshake" else 0),
        "status": "ok",
        "result": {
            "operations": operations,
            "custom_svg_display": True,
            "ocr": False,
            "png_export": True,
            "descendant_pid": descendant.pid if descendant else None
        } if operation == "handshake" else {}
    }
    if operation == "handshake":
        if mode == "no-parse": response["result"]["operations"] = [op for op in operations if op != "parse"]
        if mode == "bad-png": response["result"]["png_export"] = "yes"
    elif operation == "parse":
        response["result"] = {"operation": "parse", "diagnostics": [], "source_offset_unit": "codepoint"}
    elif operation == "transcribe":
        response["result"] = {"payload": request["payload"]}
    if mode.startswith("progress") and operation == "transcribe" or mode == "progress-on-render" and operation == "render":
        frames = [(0, 2, "recognizing"), (1, 2, "recognizing"), (2, 2, "compiling")]
        if mode == "progress-regression": frames = [(1, 2, "recognizing"), (0, 2, "recognizing")]
        if mode == "progress-total": frames = [(0, 2, "recognizing"), (1, 3, "recognizing")]
        if mode == "progress-stage": frames = [(0, 2, "unknown")]
        if mode == "progress-early-compile": frames = [(0, 2, "compiling")]
        if mode == "progress-after-compile": frames = [(2, 2, "compiling"), (2, 2, "recognizing")]
        if mode == "progress-bool": frames = [(True, 2, "recognizing")]
        if mode == "progress-flood": frames = [(0, 1, "recognizing")] * 20
        for completed, total, stage in frames:
            frame = {**response, "status": "progress", "result": {"completed": completed, "total": total, "stage": stage}}
            if mode == "progress-id": frame["request_id"] = "stale"
            if mode == "progress-revision": frame["document_revision"] += 1
            if mode == "progress-generation": frame["engine_generation"] = "old-worker"
            print(json.dumps(frame), flush=True)
        response["result"] = {"jps": "Q: 1 |", "issues": [], "page_count": 3 if mode == "progress-final-total" else 2}
        if mode == "progress-error":
            response.pop("result")
            response.update(status="error", error={"code":"ocr_failed","message":"recognition failed"})
    print(json.dumps(response), flush=True)
    if mode == "exit-after-handshake" and operation == "handshake":
        sys.exit(0)
"#;

    fn fake_engine(mode: &str) -> EngineSupervisor {
        let interpreter = if cfg!(windows) { "python" } else { "python3" };
        EngineSupervisor::test_command(
            interpreter,
            &["-u", "-c", FAKE_ENGINE, mode],
            Duration::from_secs(2),
        )
    }

    fn render_args() -> RenderArgs {
        RenderArgs {
            document_id: "lifecycle-test".into(),
            document_revision: 1,
            name: "test.jps".into(),
            code: "Q: 1 |".into(),
            custom_code: String::new(),
            page_config: json!({}),
        }
    }

    fn assert_reaped(child: &Arc<Mutex<WorkerProcess>>) {
        assert!(child.lock().unwrap().child.try_wait().unwrap().is_some());
    }

    #[cfg(target_os = "linux")]
    fn descendant_running(pid: u32) -> bool {
        std::fs::read_to_string(format!("/proc/{pid}/stat"))
            .ok()
            .and_then(|stat| {
                stat.rsplit_once(')')
                    .map(|(_, rest)| rest.trim().starts_with('Z'))
            })
            == Some(false)
    }

    #[cfg(all(unix, not(target_os = "linux")))]
    fn descendant_running(pid: u32) -> bool {
        // SAFETY: signal zero only checks whether this test's child is alive.
        unsafe { libc::kill(pid as i32, 0) == 0 }
    }

    #[cfg(windows)]
    fn descendant_running(pid: u32) -> bool {
        use windows_sys::Win32::Foundation::CloseHandle;
        use windows_sys::Win32::System::Threading::{
            GetExitCodeProcess, OpenProcess, PROCESS_QUERY_LIMITED_INFORMATION,
        };
        // SAFETY: read-only query of the PID returned by this test's worker.
        let handle = unsafe { OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid) };
        if handle.is_null() {
            return false;
        }
        let mut code = 0;
        // SAFETY: handle and output buffer are valid; close our sole handle after the query.
        let running = unsafe { GetExitCodeProcess(handle, &mut code) != 0 && code == 259 };
        unsafe { CloseHandle(handle) };
        running
    }

    #[test]
    fn shutdown_timeout_crash_and_protocol_errors_stop_descendants() {
        for mode in [
            "normal",
            "hang-request",
            "exit-after-handshake",
            "bad-response",
        ] {
            let mut engine = fake_engine(&format!("child-{mode}"));
            let pid = engine.capabilities().unwrap()["descendant_pid"]
                .as_u64()
                .unwrap() as u32;
            assert!(descendant_running(pid));
            if mode != "normal" {
                assert!(engine.render(render_args()).is_err());
            }
            drop(engine);
            let deadline = Instant::now() + Duration::from_secs(2);
            while descendant_running(pid) && Instant::now() < deadline {
                std::thread::sleep(Duration::from_millis(10));
            }
            assert!(
                !descendant_running(pid),
                "{mode} left descendant {pid} running"
            );
        }
    }

    #[test]
    fn bounded_line_accepts_exact_limit_and_rejects_overflow() {
        let mut exact = BufReader::new(Cursor::new(b"abc\n"));
        assert_eq!(read_bounded_line(&mut exact, 4).unwrap(), b"abc\n");
        let mut oversized = BufReader::new(Cursor::new(b"abcd\n"));
        assert_eq!(
            read_bounded_line(&mut oversized, 4).unwrap_err().kind(),
            ErrorKind::InvalidData
        );
    }

    #[test]
    fn response_identity_and_generation_are_checked() {
        let response = json!({
            "protocol_version": "1.7.0",
            "engine_generation": "g1",
            "request_id": "r1",
            "document_id": "d1",
            "document_revision": 2,
            "status": "ok",
            "result": {}
        });
        assert!(validate_response(&response, "r1", "d1", 2, Some("g1"), false).is_ok());
        assert!(validate_response(&response, "r1", "d1", 3, Some("g1"), false).is_err());
        assert!(validate_response(&response, "r1", "d1", 2, Some("g2"), false).is_err());
    }

    #[test]
    fn handshake_requires_boolean_feature_capabilities() {
        let response = json!({
            "protocol_version": "1.7.0",
            "engine_generation": "g1",
            "request_id": "handshake-0",
            "document_id": "desktop",
            "document_revision": 0,
            "status": "ok",
            "result": {
                "operations": [
                    "handshake", "load_document", "render", "parse", "export_svg",
                    "render_page", "serialize_document", "transcribe"
                ],
                "custom_svg_display": true,
                "ocr": false,
                "png_export": true
            }
        });
        assert!(validate_response(&response, "handshake-0", "desktop", 0, None, true).is_ok());

        let mut invalid = response;
        invalid["result"]["ocr"] = json!("unknown");
        assert!(validate_response(&invalid, "handshake-0", "desktop", 0, None, true).is_err());
    }

    fn transcription_args() -> TranscribeArgs {
        TranscribeArgs {
            document_id: "transcription-doc".into(),
            document_revision: 7,
            path: "/managed/reference.pdf".into(),
        }
    }

    #[test]
    fn parse_routes_the_snapshot_and_handshake_rejects_missing_parse_or_bad_png() {
        let mut engine = fake_engine("normal");
        let result = engine.parse(render_args()).unwrap();
        assert_eq!(result["result"]["operation"], "parse");
        assert_eq!(result["document_id"], "lifecycle-test");
        assert_eq!(result["document_revision"], 1);
        for mode in ["no-parse", "bad-png"] {
            let mut invalid = fake_engine(mode);
            assert!(invalid.capabilities().is_err());
            assert!(invalid.process.is_none());
        }
    }

    #[test]
    fn valid_transcription_progress_is_correlated_monotonic_and_retains_business_errors() {
        for mode in ["progress", "progress-error"] {
            let mut engine = fake_engine(mode);
            let received = Arc::new(Mutex::new(Vec::new()));
            let frames = Arc::clone(&received);
            let result = engine
                .transcribe_with_progress(
                    transcription_args(),
                    Arc::new(AtomicBool::new(false)),
                    move |frame| frames.lock().unwrap().push(frame),
                )
                .unwrap();
            assert_eq!(result["document_id"], "transcription-doc");
            assert_eq!(result["document_revision"], 7);
            let frames = received.lock().unwrap();
            assert_eq!(frames.len(), 3);
            assert_eq!(frames[0]["completed"], 0);
            assert_eq!(frames[1]["completed"], 1);
            assert_eq!(frames[2]["stage"], "compiling");
            if mode == "progress-error" {
                assert_eq!(result["status"], "error");
                assert_eq!(result["error"]["code"], "ocr_failed");
            } else {
                assert_eq!(result["status"], "ok");
            }
            assert!(engine.parse(render_args()).is_ok());
        }
    }

    #[test]
    fn transcription_request_sends_only_the_managed_reference_path() {
        let mut engine = fake_engine("normal");
        let result = engine.transcribe(transcription_args()).unwrap();
        assert_eq!(
            result["result"]["payload"]["path"],
            "/managed/reference.pdf"
        );
        assert_eq!(result["result"]["payload"].as_object().unwrap().len(), 1);
    }

    #[test]
    fn invalid_progress_stops_the_worker_and_cannot_leak_to_another_request() {
        for mode in [
            "progress-id",
            "progress-revision",
            "progress-generation",
            "progress-regression",
            "progress-total",
            "progress-stage",
            "progress-early-compile",
            "progress-after-compile",
            "progress-bool",
            "progress-flood",
            "progress-final-total",
            "progress-on-render",
        ] {
            let mut engine = fake_engine(mode);
            engine.capabilities().unwrap();
            let child = Arc::clone(&engine.process.as_ref().unwrap().child);
            let result = if mode == "progress-on-render" {
                engine.render(render_args())
            } else {
                engine.transcribe_with_progress(
                    transcription_args(),
                    Arc::new(AtomicBool::new(false)),
                    |_| {},
                )
            };
            assert!(result.is_err(), "accepted {mode}");
            assert_reaped(&child);
            assert!(engine.process.is_none());
            assert!(
                engine.parse(render_args()).is_ok(),
                "cannot restart after {mode}"
            );
        }
    }

    #[test]
    fn pre_cancelled_transcription_never_starts_a_worker() {
        let mut engine = fake_engine("normal");
        let result = engine.transcribe_with_progress(
            transcription_args(),
            Arc::new(AtomicBool::new(true)),
            |_| {},
        );
        assert!(result.unwrap_err().contains("cancelled"));
        assert!(engine.process.is_none());
        assert!(engine.parse(render_args()).is_ok());
    }

    #[test]
    fn running_cancellation_kills_worker_descendants_promptly_and_restarts() {
        let mut engine = fake_engine("child-hang-request");
        let pid = engine.capabilities().unwrap()["descendant_pid"]
            .as_u64()
            .unwrap() as u32;
        let child = Arc::clone(&engine.process.as_ref().unwrap().child);
        let cancelled = Arc::new(AtomicBool::new(false));
        let flag = Arc::clone(&cancelled);
        let cancel = std::thread::spawn(move || {
            std::thread::sleep(Duration::from_millis(100));
            flag.store(true, Ordering::Release);
        });
        let started = Instant::now();
        let result = engine.transcribe_with_progress(transcription_args(), cancelled, |_| {});
        cancel.join().unwrap();
        assert!(result.unwrap_err().contains("cancelled"));
        assert!(started.elapsed() < Duration::from_secs(2));
        assert_reaped(&child);
        assert!(!descendant_running(pid));
        assert!(engine.capabilities().is_ok());
    }

    #[test]
    fn cancellation_during_handshake_kills_the_started_process_tree() {
        let path = std::env::temp_dir().join(format!(
            "octopus-startup-cancel-{}-{}",
            std::process::id(),
            super::NEXT_REQUEST_ID.fetch_add(1, Ordering::Relaxed)
        ));
        let path_text = path.to_str().unwrap();
        let interpreter = if cfg!(windows) { "python" } else { "python3" };
        let mut engine = EngineSupervisor::test_command(
            interpreter,
            &["-u", "-c", FAKE_ENGINE, "child-hang-handshake", path_text],
            Duration::from_secs(5),
        );
        let cancelled = Arc::new(AtomicBool::new(false));
        let flag = Arc::clone(&cancelled);
        let created = path.clone();
        let cancel = std::thread::spawn(move || {
            let deadline = Instant::now() + Duration::from_secs(2);
            while !created.exists() && Instant::now() < deadline {
                std::thread::sleep(Duration::from_millis(5));
            }
            // Publication can precede json.dump by a moment; wait for its close.
            std::thread::sleep(Duration::from_millis(30));
            flag.store(true, Ordering::Release);
        });
        let started = Instant::now();
        let result = engine.transcribe_with_progress(transcription_args(), cancelled, |_| {});
        cancel.join().unwrap();
        assert!(result.unwrap_err().contains("cancelled"));
        assert!(started.elapsed() < Duration::from_secs(3));
        assert!(engine.process.is_none());
        let pids: Vec<u32> = serde_json::from_slice(&std::fs::read(&path).unwrap()).unwrap();
        std::fs::remove_file(path).unwrap();
        assert!(pids.iter().all(|pid| !descendant_running(*pid)));
    }

    #[test]
    fn shutdown_kills_and_reaps_the_worker() {
        let mut engine = fake_engine("normal");
        engine.capabilities().unwrap();
        let child = Arc::clone(&engine.process.as_ref().unwrap().child);

        drop(engine);

        assert_reaped(&child);
    }

    #[test]
    fn shutdown_signal_interrupts_a_request_and_prevents_restarting_workers() {
        let mut engine = fake_engine("child-hang-request");
        let pid = engine.capabilities().unwrap()["descendant_pid"]
            .as_u64()
            .unwrap() as u32;
        let child = Arc::clone(&engine.process.as_ref().unwrap().child);
        let signal = engine.shutdown_signal();
        let stop = std::thread::spawn(move || {
            std::thread::sleep(Duration::from_millis(100));
            signal.store(true, Ordering::Release);
        });
        let started = Instant::now();
        assert!(engine
            .render(render_args())
            .unwrap_err()
            .contains("shut down"));
        stop.join().unwrap();
        assert!(started.elapsed() < Duration::from_secs(1));
        engine.shutdown();
        assert_reaped(&child);
        assert!(!descendant_running(pid));
        assert!(engine.capabilities().unwrap_err().contains("shut down"));
        assert!(engine
            .render(render_args())
            .unwrap_err()
            .contains("shut down"));
    }

    #[test]
    fn bad_handshake_is_rejected_without_caching_a_worker() {
        let mut engine = fake_engine("bad-version");

        let error = engine.capabilities().unwrap_err();

        assert!(error.contains("protocol, identity, status, or generation mismatch"));
        assert!(engine.process.is_none());
    }

    #[test]
    fn timed_out_startup_stops_the_worker_and_returns() {
        let mut engine = fake_engine("hang-handshake");
        let started = Instant::now();

        let error = engine.capabilities().unwrap_err();

        assert!(error.contains("handshake timed out or stopped"));
        assert!(started.elapsed() < Duration::from_secs(5));
        assert!(engine.process.is_none());
    }

    #[test]
    fn exited_worker_is_reaped_and_restarted() {
        let mut engine = fake_engine("exit-after-handshake");
        engine.capabilities().unwrap();
        let child = Arc::clone(&engine.process.as_ref().unwrap().child);

        assert!(engine.render(render_args()).is_err());
        assert_reaped(&child);
        assert!(engine.capabilities().is_ok());
    }

    #[test]
    fn hung_request_is_killed_reaped_and_restartable() {
        let mut engine = fake_engine("hang-request");
        engine.capabilities().unwrap();
        let child = Arc::clone(&engine.process.as_ref().unwrap().child);

        let started = Instant::now();
        let error = engine.render(render_args()).unwrap_err();

        assert!(error.contains("timed out or stopped"));
        assert!(started.elapsed() < Duration::from_secs(5));
        assert_reaped(&child);
        assert!(engine.capabilities().is_ok());
    }

    #[test]
    fn missing_packaged_engine_never_falls_back_to_development_tools() {
        let executable =
            std::env::temp_dir().join(format!("octopus-missing-engine-{}", std::process::id()));
        let mut engine = EngineSupervisor::packaged(executable);

        assert!(engine
            .capabilities()
            .unwrap_err()
            .contains("executable is missing"));
        assert!(engine.process.is_none());
    }

    #[cfg(not(debug_assertions))]
    #[test]
    fn release_default_requires_a_packaged_engine() {
        let mut engine = EngineSupervisor::default();

        assert!(engine
            .capabilities()
            .unwrap_err()
            .contains("resource is not configured"));
    }
}
