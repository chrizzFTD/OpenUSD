# grill-usd-core

**Unofficial, experimental WebAssembly (Pyodide) build of
[Pixar's OpenUSD](https://openusd.org) Python bindings.**

> This package is **not** affiliated with or endorsed by Pixar Animation
> Studios, and it is **not** the official
> [`usd-core`](https://pypi.org/project/usd-core/) package. It is the testing
> distribution channel for the Pyodide/wasm build of the `usd-core` module set,
> maintained in the [chrizzFTD/OpenUSD fork](https://github.com/chrizzFTD/OpenUSD)
> for the [grill](https://github.com/thegrill/grill) /
> [pyrepl-web](https://github.com/chrizzFTD/pyrepl-web/tree/grill) tooling.

## What it is

The complete `usd-core` Python module set (`Tf`, `Sdf`, `Usd`, `UsdGeom`, … —
no imaging), cross-compiled to `wasm32` for **Pyodide 314** (CPython 3.14,
Emscripten ABI `2026_0`, [PEP 783](https://peps.python.org/pep-0783/)
`pyemscripten_2026_0_wasm32` wheel tag).

The C++ core ships once as a shared `libusd_ms.so` Emscripten side module
vendored in `grill_usd_core.libs/`, with thin `_*.so` extension modules
dynamically linking against it, plus the USD plugin registry under
`pxr/pluginfo/`.

## Installing

In a Pyodide 314 runtime (browser or Node):

```python
import micropip
await micropip.install("grill-usd-core")
```

Or with [pyrepl-web](https://github.com/chrizzFTD/pyrepl-web/tree/grill):

```html
<py-repl packages="grill-usd-core"></py-repl>
```

Or natively into a [`pyodide venv`](https://pyodide.org/en/stable/usage/building-and-testing-packages.html):

```bash
pyodide venv .venv-pyodide
.venv-pyodide/bin/pip install grill-usd-core
```

## Usage

The import name is **`pxr`**, exactly like the official `usd-core`:

```python
from pxr import Usd, UsdGeom

stage = Usd.Stage.CreateInMemory()
world = UsdGeom.Xform.Define(stage, "/World")
cube = UsdGeom.Cube.Define(stage, "/World/Cube")
stage.SetDefaultPrim(world.GetPrim())
print(stage.GetRootLayer().ExportToString())
```

## Caveats

- **WebAssembly only.** The wheel is `pyemscripten_2026_0_wasm32` — it installs
  only under Pyodide 314 / Python 3.14 on Emscripten. There are no native
  (Linux/macOS/Windows) wheels here; use the official `usd-core` for those.
- **Cannot coexist with `usd-core`.** Both distributions own the `pxr` import
  package, so they cannot be installed into the same environment. In practice
  this never conflicts: `usd-core` publishes no Emscripten wheels.
- **Experimental.** This is an alpha-quality testing build; APIs match the
  upstream OpenUSD release it was built from, but the wasm port itself is
  young. No imaging (`UsdImagingGL`/`usdview`), no `usdGenSchema`/CLI tools.

## Source and build

Built from the [chrizzFTD/OpenUSD fork](https://github.com/chrizzFTD/OpenUSD)
(`build_scripts/pyodide/`); see
[`docs/pyodide/PLAN.md`](https://github.com/chrizzFTD/OpenUSD/blob/release/docs/pyodide/PLAN.md)
for the roadmap and a browser demo under `extras/pyodide/demo/`.

OpenUSD is licensed under the Tomorrow Open Source Technology License 1.0
(`LicenseRef-TOST-1.0`); see the bundled `LICENSE.txt`.
