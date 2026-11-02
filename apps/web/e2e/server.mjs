// Playwright servers with the same isolated environment on macOS and Windows.
import { rmSync } from "node:fs";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
const root = fileURLToPath(new URL("../../../", import.meta.url));
const data = fileURLToPath(new URL("../../../.e2e-data/", import.meta.url));
const api = process.argv[2] === "api";
if (api) rmSync(data, { recursive: true, force: true });
const python = process.env.POLYMECH_TEST_PYTHON;
const command = api ? (python || "uv") : process.execPath;
const args = api
  ? [...(python ? ["-m"] : ["run", "--project", root]), "uvicorn", "polymech_api.main:app", "--host", "127.0.0.1", "--port", "8775"]
  : [fileURLToPath(new URL("../node_modules/vite/bin/vite.js", import.meta.url)), "--port", "5174", "--strictPort"];
const child = spawn(command, args, {
  cwd: api ? root : fileURLToPath(new URL("../", import.meta.url)),
  env: { ...process.env, POLYMECH_DATA_DIR: data, POLYMECH_NO_KEYCHAIN: "1", POLYMECH_API_PORT: "8775", PYTHONUTF8: "1" },
  stdio: "inherit", windowsHide: true,
});
child.on("error", (error) => { console.error(error); process.exit(1); });
child.on("exit", (code) => process.exit(code ?? 1));
for (const signal of ["SIGTERM", "SIGINT"]) process.on(signal, () => child.kill(signal));
