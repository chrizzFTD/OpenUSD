/**
 * PR-A smoke test: import pxr.Tf under Pyodide 314 (Node harness).
 *
 * Usage (from repo root, after package_tf_spike_wheel.py):
 *   node build_scripts/pyodide/test_tf_import.mjs dist/pyodide/*.whl
 *
 * Uses the pyodide xbuildenv runtime (file:// indexURL). Set PYODIDE_ROOT or
 * run `pyodide xbuildenv use 314.0.2` before this script.
 */
import { createServer } from "node:http";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { loadPyodide } from "pyodide";

const __dirname = dirname(fileURLToPath(import.meta.url));

function serveWheel(wheelPath) {
  const wheelBytes = readFileSync(wheelPath);
  const wheelName = wheelPath.split("/").pop();
  return new Promise((resolveUrl) => {
    const server = createServer((req, res) => {
      res.writeHead(200, { "Content-Type": "application/zip" });
      res.end(wheelBytes);
    });
    server.listen(0, "127.0.0.1", () => {
      const { port } = server.address();
      resolveUrl({
        url: `http://127.0.0.1:${port}/${wheelName}`,
        close: () => server.close(),
      });
    });
  });
}

async function main() {
  const wheelArg = process.argv[2];
  if (!wheelArg) {
    console.error("Usage: node test_tf_import.mjs <path-to-wheel>");
    process.exit(1);
  }
  const wheelPath = resolve(wheelArg);
  const { url, close } = await serveWheel(wheelPath);

  console.log(`Loading Pyodide 314 and installing wheel from ${url}`);
  console.log("Loading Pyodide 314 …");
  const pyodide = await loadPyodide();

  await pyodide.loadPackage("micropip");
  await pyodide.runPythonAsync(`
import micropip
await micropip.install("${url}")
`);

  const result = await pyodide.runPythonAsync(`
from pxr import Tf
Tf.StringSplit("hello,world", ",")
`);
  console.log("from pxr import Tf -> OK");
  console.log("Tf.StringSplit('hello,world', ',') =", result);

  close();
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
