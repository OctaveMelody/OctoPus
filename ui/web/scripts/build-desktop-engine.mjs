import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repositoryRoot = fileURLToPath(new URL("../../..", import.meta.url));
const buildEnvironment = path.join(
  repositoryRoot,
  "build",
  "desktop-build-venv",
);
const buildScript = path.join(repositoryRoot, "build_desktop_engine.py");
const result = spawnSync(
  "uv",
  [
    "run",
    "--python",
    "3.12",
    "--locked",
    "--project",
    repositoryRoot,
    "--extra",
    "desktop-build",
    "--extra",
    "transcription",
    "python",
    buildScript,
  ],
  {
    cwd: repositoryRoot,
    env: { ...process.env, UV_PROJECT_ENVIRONMENT: buildEnvironment },
    stdio: "inherit",
  },
);

if (result.error) {
  throw new Error(`could not run the desktop engine builder: ${result.error.message}`);
}
process.exitCode = result.status ?? 1;
