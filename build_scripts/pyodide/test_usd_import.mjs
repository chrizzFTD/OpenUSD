/**
 * Smoke test: import the full usd-core module set under Pyodide 314 and
 * author + serialize a stage round-trip (Node harness, no browser).
 *
 * Usage (from repo root, after package_wheel.py):
 *   node build_scripts/pyodide/test_usd_import.mjs dist/pyodide/grill_usd_core-*.whl
 *
 * Or against a published package (PR-C; e.g. the TestPyPI/PyPI validation):
 *   node build_scripts/pyodide/test_usd_import.mjs grill-usd-core
 *   node build_scripts/pyodide/test_usd_import.mjs grill-usd-core \
 *       https://test.pypi.org/simple
 *
 * Set TF_DEBUG=PLUG_INFO_SEARCH in the environment to trace plugin discovery.
 *
 * Exercises:
 *   - the shared libusd_ms.so side module loading via RPATH,
 *   - runtime plugin discovery (Sdf usda/usdc file formats + Ar resolver),
 *   - cross-module Boost.Python type flow (Sdf.Path / Gf into UsdGeom),
 *   - authoring + .usda serialization round-trip.
 */
import { createServer } from "node:http";
import { existsSync, readFileSync } from "node:fs";
import { basename, resolve } from "node:path";
import { loadPyodide } from "pyodide";

function serveWheel(wheelPath) {
  const wheelBytes = readFileSync(wheelPath);
  const wheelName = basename(wheelPath);
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

const TEST_SNIPPET = `
from pxr import Usd, UsdGeom, Sdf, Gf

# Gate: shared side module + plugin registry (no TF_FATAL_ERROR here).
anon = Sdf.Layer.CreateAnonymous()
assert anon is not None, "Sdf.Layer.CreateAnonymous returned None"

stage = Usd.Stage.CreateInMemory()          # exercises Sdf usda file format plugin
world = UsdGeom.Xform.Define(stage, "/World")
cube = UsdGeom.Cube.Define(stage, "/World/Cube")
cube.GetSizeAttr().Set(2.0)

# Cross-module Boost.Python type flow: Gf.Vec3d -> UsdGeom op -> Sdf value.
UsdGeom.XformCommonAPI(world).SetTranslate(Gf.Vec3d(1.0, 2.0, 3.0))
stage.SetDefaultPrim(world.GetPrim())

usda = stage.GetRootLayer().ExportToString()   # serialize round-trip
assert "def Xform \\"World\\"" in usda, usda
assert "def Cube \\"Cube\\"" in usda, usda
assert "double size = 2" in usda, usda

# Round-trip: reimport the serialized text into a fresh layer.
layer = Sdf.Layer.CreateAnonymous(".usda")
assert layer.ImportFromString(usda), "ImportFromString failed"
reloaded = Usd.Stage.Open(layer)
assert reloaded.GetPrimAtPath("/World/Cube"), "round-trip prim missing"

usda
`;

async function main() {
  const wheelArg = process.argv[2];
  const indexUrl = process.argv[3];
  if (!wheelArg) {
    console.error(
      "Usage: node test_usd_import.mjs <path-to-wheel | package-name> [index-url]",
    );
    process.exit(1);
  }

  // A .whl on disk is served over a local HTTP server; anything else is a
  // requirement resolved by micropip from PyPI (or index-url, e.g. TestPyPI).
  let installTarget;
  let close = () => {};
  if (wheelArg.endsWith(".whl") && existsSync(resolve(wheelArg))) {
    ({ url: installTarget, close } = await serveWheel(resolve(wheelArg)));
  } else {
    installTarget = wheelArg;
  }
  const indexKwarg = indexUrl ? `, index_urls=["${indexUrl}"]` : "";

  console.log(
    `Loading Pyodide 314 and installing ${installTarget}` +
      (indexUrl ? ` from ${indexUrl}` : ""),
  );
  const pyodide = await loadPyodide();

  await pyodide.loadPackage("micropip");
  await pyodide.runPythonAsync(`
import micropip
await micropip.install("${installTarget}"${indexKwarg})
`);

  const usda = await pyodide.runPythonAsync(TEST_SNIPPET);
  console.log("from pxr import Usd, UsdGeom, Sdf, Gf -> OK");
  console.log("Authored + serialized stage round-trip -> OK\n");
  console.log("----- stage .usda -----");
  console.log(usda);
  console.log("-----------------------");

  close();
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
