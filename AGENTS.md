# AGENTS.md

## Cursor Cloud specific instructions

### Scope of this environment

This Cloud Agent environment is provisioned for the **OpenUSD Pyodide cross-build**
work (browser `usd-core` Python bindings via Pyodide 314 / Emscripten 5.0.3). The
Pyodide build code and docs live on the fork's pyodide branches
(`build_scripts/pyodide/`, `docs/pyodide/`, `extras/pyodide/`), not on `release`.
Start from `docs/pyodide/PLAN.md` and `docs/pyodide/PR-B-PLAN.md` for context.

This scope does **not** include the full native (Linux) OpenUSD C++/CMake build or
its CTest suite — only the Pyodide/wasm cross-build toolchain.

### Toolchain (baked into the snapshot)

The following are pre-installed in the VM snapshot; the startup update script only
refreshes them and does not re-download the heavy pieces:

- `pyodide-build`, `jinja2`, `wheel` (host Python 3.12, pip user site `~/.local`).
- Pyodide cross-build environment `314.0.2` (`pyodide xbuildenv install 314.0.2`)
  → Python 3.14.2, ABI `2026_0`, cached under `~/.cache/pyodide-build/`.
- Emscripten SDK `5.0.3` (`pyodide xbuildenv install-emscripten`), also under
  `~/.cache/pyodide-build/`.
- Node `pyodide` package in `build_scripts/pyodide/node_modules` (for the smoke test).

`pyodide config list` should report `python_version="3.14.2"`,
`emscripten_version="5.0.3"`, `pyodide_abi_version="2026_0"`. If the active env is
not selected after a fresh VM, run `pyodide xbuildenv use 314.0.2` (no download).

### Non-obvious gotchas

- **PATH**: the `pyodide` CLI installs to `~/.local/bin`, which is added to PATH in
  `~/.bashrc`. Non-login/non-interactive shells may not source it — call
  `~/.local/bin/pyodide` directly or prepend `~/.local/bin` to PATH if `pyodide`
  is not found.
- **Do not manually source `emsdk_env.sh`** before running the build script:
  `build_scripts/pyodide/build_spike.py` discovers `emsdk_dir` via
  `pyodide config get` and sources `emsdk_env.sh` itself. (If you compile by hand,
  `source "$(pyodide config get emsdk_dir)/emsdk_env.sh"` first.)
- **`jinja2` "missing dependency" warning at configure time is expected and
  harmless here**: `build_spike.py` points `Python3_EXECUTABLE` at the cross
  Pyodide interpreter, which is what CMake's `FindJinja2` probes — that interpreter
  has no `jinja2`. Host Python *does* have `jinja2` (required only for schema
  regeneration via `usdGenSchema`, which the `_tf`/monolith spike does not need
  because USD ships pre-generated schema code).

### Build / test commands (Pyodide)

Run from the repo root (a pyodide branch that contains `build_scripts/pyodide/`):

- Validate the toolchain / CMake configure only (fast, builds oneTBB to wasm once):
  `python3 build_scripts/pyodide/build_spike.py --configure-only`
- Build the `_tf` module (full USD monolith emscripten compile — long-running):
  `python3 build_scripts/pyodide/build_spike.py --skip-onetbb --build-target _tf`
  (`--skip-onetbb` reuses the oneTBB build in `build/pyodide-spike/tbb`).
- Package the spike wheel: `python3 build_scripts/pyodide/package_tf_spike_wheel.py …`
- Node smoke test of a built wheel (no browser):
  `node build_scripts/pyodide/test_tf_import.mjs <path-to-wheel>` — loads the
  Pyodide 314 runtime from the Node `pyodide` package and asserts `from pxr import Tf`.
