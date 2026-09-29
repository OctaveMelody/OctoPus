use serde::Deserialize;
use serde_json::{json, Value};
#[cfg(test)]
use std::ffi::OsString;
use std::io::{self, BufRead, BufReader, BufWriter, Write};
#[cfg(debug_assertions)]
use std::path::Path;
use std::path::PathBuf;
use std::process::{ChildStdin, ChildStdout, Command, Stdio};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{mpsc, Arc, Mutex};
use std::thread::{self, JoinHandle};
use std::time::Duration;

mod process;
use process::WorkerProcess;

const PROTOCOL_VERSION: &str = "1.6.0";
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

struct WorkerMessage {
    request: Vec<u8>,
    request_id: String,
    document_id: String,
    revision: u64,
    reply: mpsc::SyncSender<Result<Value, String>>,
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
        }
    }
}

impl EngineSupervisor {
    pub fn packaged(executable: PathBuf) -> Self {
        Self {
            process: None,
            launch: EngineLaunch::Packaged(executable),
            request_timeout: REQUEST_TIMEOUT,
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
        }
    }

    pub fn capabilities(&mut self) -> Result<Value, String> {
        if self.process.is_none() {
            self.process = Some(EngineProcess::spawn(&self.launch, self.request_timeout)?);
        }
        Ok(self
            .process
            .as_ref()
            .expect("engine was spawned")
            .capabilities
            .clone())
    }

    pub fn render(&mut self, args: RenderArgs) -> Result<Value, String> {
        self.render_with_operation(args, "render")
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
        self.call_with_timeout(
            args.document_id,
            args.document_revision,
            "transcribe",
            json!({ "path": args.path }),
            Duration::from_secs(900),
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
            self.process = Some(EngineProcess::spawn(&self.launch, self.request_timeout)?);
        }
        let process = self.process.as_mut().expect("engine was spawned");
        let result = process.request(request, request_id, document_id, revision, timeout);
        if result.is_err() {
            self.process.take();
        }
        result
    }
}

impl EngineProcess {
    fn spawn(launch: &EngineLaunch, request_timeout: Duration) -> Result<Self, String> {
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
        let capabilities = match startup_receiver.recv_timeout(request_timeout) {
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

    fn request(
        &mut self,
        request: Vec<u8>,
        request_id: String,
        document_id: String,
        revision: u64,
        timeout: Duration,
    ) -> Result<Value, String> {
        let (reply, receiver) = mpsc::sync_channel(1);
        self.sender
            .send(WorkerCommand::Request(WorkerMessage {
                request,
                request_id,
                document_id,
                revision,
                reply,
            }))
            .map_err(|_| "Python worker stopped".to_owned())?;
        match receiver.recv_timeout(timeout) {
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
            let value = read_response(&mut reader)?;
            validate_response(
                &value,
                &message.request_id,
                &message.document_id,
                message.revision,
                Some(&generation),
                false,
            )?;
            Ok(value)
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
                    "export_svg",
                    "render_page",
                    "serialize_document",
                    "transcribe",
                ]
                .iter()
                .all(|expected| operations.iter().any(|operation| operation == expected))
            }) || !result["custom_svg_display"].is_boolean()
                || !result["ocr"].is_boolean()
                || !result["lilypond"].is_boolean())
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
    use super::{read_bounded_line, validate_response, EngineSupervisor, RenderArgs};
    use serde_json::json;
    use std::io::{BufReader, Cursor, ErrorKind};
    use std::sync::{Arc, Mutex};
    use std::time::{Duration, Instant};

    const FAKE_ENGINE: &str = r#"
import json, subprocess, sys, time
mode = sys.argv[1]
descendant = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"]) if mode.startswith("child-") else None
mode = mode.removeprefix("child-")
operations = ["handshake", "load_document", "render", "export_svg", "render_page", "serialize_document", "transcribe"]
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
            "lilypond": False,
            "descendant_pid": descendant.pid if descendant else None
        } if operation == "handshake" else {}
    }
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
            "protocol_version": "1.6.0",
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
            "protocol_version": "1.6.0",
            "engine_generation": "g1",
            "request_id": "handshake-0",
            "document_id": "desktop",
            "document_revision": 0,
            "status": "ok",
            "result": {
                "operations": [
                    "handshake", "load_document", "render", "export_svg",
                    "render_page", "serialize_document", "transcribe"
                ],
                "custom_svg_display": true,
                "ocr": false,
                "lilypond": false
            }
        });
        assert!(validate_response(&response, "handshake-0", "desktop", 0, None, true).is_ok());

        let mut invalid = response;
        invalid["result"]["ocr"] = json!("unknown");
        assert!(validate_response(&invalid, "handshake-0", "desktop", 0, None, true).is_err());
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
            std::env::temp_dir().join(format!("re-tomato-missing-engine-{}", std::process::id()));
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
