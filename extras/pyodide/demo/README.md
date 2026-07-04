# OpenUSD Pyodide browser demo (PR-B)

Interactive browser demo for the full `grill-usd-core` Pyodide 314 wheel using
**[pyrepl-web `grill`](https://github.com/chrizzFTD/pyrepl-web/tree/grill)** as the
REPL runtime. No changes to pyrepl-web — only consume its built `pyrepl.js`.

The wheel ships the OpenUSD C++ core once as a shared `libusd_ms.so`
(`-sSIDE_MODULE=1`) vendored in `.libs/`, with thin `_*.so` extensions
dynamically linking against it, plus the plugin registry under `pxr/pluginfo/`.

## Prerequisites

1. **Build the full USD install tree** (shared `libusd_ms.so` + all `_*.so`):

   ```bash
   pip install 'pyodide-build>=0.36' jinja2 wheel
   pyodide xbuildenv install 314.0.2 --force && pyodide xbuildenv use 314.0.2
   pyodide xbuildenv install-emscripten
   python build_scripts/pyodide/build_spike.py --build-target install \
       --build-root build/pyodide-spike
   ```

   (Use `--skip-onetbb` after the first successful oneTBB build.)

2. **Package the wheel** and copy it here:

   ```bash
   python build_scripts/pyodide/package_wheel.py \
       --build-root build/pyodide-spike \
       --output-dir dist/pyodide
   cp dist/pyodide/grill_usd_core-*.whl extras/pyodide/demo/
   ```

   Then update the `packages="./grill_usd_core-<ver>-...whl"` filename in
   `index.html` to match the copied wheel version.

3. **pyrepl-web `grill`** (sibling clone, build once):

   ```bash
   git clone -b grill https://github.com/chrizzFTD/pyrepl-web.git ../pyrepl-web
   cd ../pyrepl-web && bun install && bun run build
   ```

## Serve the demo

`server.py` serves the demo directory and the pyrepl-web build from a **single
origin** (mounting the pyrepl `dist/` under `/pyrepl/`). Single-origin serving
matters: the `pyrepl.js` wrapper does a dynamic ES-module `import()` of
`pyrepl.esm.js`, which a plain two-server `python -m http.server` setup blocks
with cross-origin CORS errors.

```bash
python3 extras/pyodide/demo/server.py \
    --pyrepl-dist ../pyrepl-web/dist   # adjust to your clone
```

Open `http://localhost:8765/index.html`.

The `packages` attribute on the `<py-repl>` element micropip-installs the
co-hosted wheel (awaited before the REPL starts); `bootstrap.py` then runs a
silent startup import and `usd_demo.py` is replayed into the REPL.

## Automated smoke test (Node, no browser)

```bash
cd build_scripts/pyodide && npm install
node test_usd_import.mjs ../../dist/pyodide/grill_usd_core-*.whl
```

Expected output: `from pxr import Usd, UsdGeom, Sdf, Gf -> OK` followed by the
serialized `.usda` stage.

## Automated smoke test (pyodide venv, no browser)

Validates the PEP 783 native install path (`pip` resolves the
`pyemscripten_2026_0_wasm32` tag inside a [`pyodide venv`](https://pyodide.org/en/stable/usage/building-and-testing-packages.html)).
Requires a *host* CPython 3.14 with `pyodide-build` (set `PYODIDE_CLI` to its
`pyodide` entry point if it is not first on `PATH`):

```bash
build_scripts/pyodide/test_pyodide_venv.sh dist/pyodide/grill_usd_core-*.whl
```

## What success looks like

- **Node harness**: `from pxr import Usd, UsdGeom, Sdf, Gf` imports, authors a
  stage, and serializes/round-trips it with no `TF_FATAL_ERROR`.
- **Browser**: pyrepl REPL runs `usd_demo.py` and prints the stage contents.
