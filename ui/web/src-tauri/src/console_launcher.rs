//! Console entry point for the Windows package. The GUI executable owns the score operations.

use jps_engine_bridge::WorkerProcess;
use std::io;
use std::process::{Command, Stdio};
use std::thread;

fn run() -> io::Result<i32> {
    let app = std::env::current_exe()?.with_file_name("octopus.exe");
    let mut command = Command::new(app);
    command
        .arg("--headless")
        .args(std::env::args_os().skip(1))
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    // The job handle also stops the headless host and its OCR children if this launcher exits.
    let mut host = WorkerProcess::spawn(command)?;
    let mut output = host.child.stdout.take().expect("configured stdout pipe");
    let mut errors = host.child.stderr.take().expect("configured stderr pipe");
    thread::scope(|scope| -> io::Result<i32> {
        let progress = scope.spawn(move || io::copy(&mut errors, &mut io::stderr().lock()));
        if let Err(error) = io::copy(&mut output, &mut io::stdout().lock()) {
            host.stop();
            return Err(error);
        }
        progress
            .join()
            .map_err(|_| io::Error::other("stderr forwarding failed"))??;
        Ok(host.child.wait()?.code().unwrap_or(1))
    })
}

fn main() {
    let code = run().unwrap_or_else(|error| {
        eprintln!("Could not run OctoPus headlessly: {error}");
        1
    });
    std::process::exit(code);
}
