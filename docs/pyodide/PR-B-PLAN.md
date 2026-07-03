# PR-B — Full `usd-core` Module Set + Private Wheel + Browser Demo

**Status:** design / implementation plan (not yet implemented)
**Branch base:** `cursor/pyodide-tf-spike-7911` (PR-A merged into the spike)
**Target branch:** `cursor/pyodide-pr-b-*`
**Scope:** all work stays in this OpenUSD fork; consume
[chrizzFTD/pyrepl-web `grill`](https://github.com/chrizzFTD/pyrepl-web/tree/grill)
as a read-only Pyodide 314 runtime.

This document is the deep architecture/design analysis and step-by-step
implementation plan for PR-B, building on the PR-A spike. It complements the
roadmap in [`PLAN.md`](./PLAN.md); read that first for constraints and context.

---

## 1. Goal recap

Ship a `usd-core`-equivalent set of Python bindings as a single
`pyemscripten_2026_0_wasm32` wheel that loads under Pyodide 314 in the browser,
so that `from pxr import Usd, UsdGeom, Sdf, …` works and a stage can be authored,
serialized (`.usda`), and round-tripped — driven from `extras/pyodide/demo/`
via pyrepl-web `grill`.

PR-A proved a *single* module (`Tf`) can load. PR-B must prove the *full graph*
of ~30 modules loads and functions, including the plugin registry that USD needs
at runtime.

---

## 2. Current state (what PR-A gives us)

PR-A established the `PXR_BUILD_PYODIDE` build mode and shipped a one-module
wheel. The relevant existing pieces:

| Area | PR-A artifact | Notes for PR-B |
|------|---------------|----------------|
| CMake option | `PXR_BUILD_PYODIDE` in `cmake/defaults/Options.cmake` | keep |
| ABI flags | `-fwasm-exceptions -sSUPPORT_LONGJMP=wasm -sUSE_PTHREADS=0 -sWASM_BIGINT` in `cmake/defaults/ProjectDefaults.cmake` | keep |
| No `-pthread` | `PXR_THREAD_LIBS=""` (`Packages.cmake`), guarded `-pthread` (`gccclangshareddefaults.cmake`) | keep |
| Extension linking | `_pxr_python_module()` adds `-sSIDE_MODULE=2` + `EXPORTED_FUNCTIONS=['_PyInit_<name>']` (`cmake/macros/Private.cmake`) | keep, generalize |
| Monolith packaging | **static** `usd_m` WHOLE_ARCHIVE'd into each `_*.so` (`cmake/macros/Public.cmake`, `_pxr_target_link_libraries`) | **must change — see §4** |
| wasm32 ABI fix | `TfPyObjWrapperStub` size/align in `pxr/base/tf/pyObjWrapper.h` | keep |
| Build driver | `build_scripts/pyodide/build_spike.py` (oneTBB + configure + `--build-target _tf`) | generalize to full build/install |
| Wheel packaging | `build_scripts/pyodide/package_tf_spike_wheel.py` (single `_tf.so`) | replace with `package_wheel.py` |
| Smoke test | `build_scripts/pyodide/test_tf_import.mjs` (Node + micropip) | extend to `Usd`/`UsdGeom` |
| Demo | `extras/pyodide/demo/` (`index.html`, `bootstrap.py`, `test_tf.py`) | extend to full `usd_demo.py` |

The configure step already sets the correct scope flags
(`PXR_BUILD_IMAGING=OFF`, `PXR_BUILD_USD_TOOLS=OFF`, `PXR_BUILD_EXEC=OFF`,
`PXR_BUILD_MONOLITHIC=ON`, `BUILD_SHARED_LIBS=ON`, `PXR_ENABLE_PYTHON_SUPPORT=ON`,
`PXR_PY_UNDEFINED_DYNAMIC_LOOKUP=ON`), so the module *set* is already correct;
what changes in PR-B is how the compiled code is **shared** and how runtime
**resources** ship.

---

## 3. The two hard problems PR-B must solve

1. **Code sharing across ~30 extension modules.** PR-A links the entire static
   `usd_m` archive into `_tf.so` with `WHOLE_ARCHIVE`. Repeating that for ~30
   modules duplicates the whole USD C++ codebase ~30× in the wheel — hundreds of
   MB, unusable in a browser. PR-B must ship the C++ core **once**.
2. **Runtime plugin discovery.** USD is not functional without its
   `plugInfo.json` registry. `Sdf` and `Ar` call `PlugRegistry::DemandPluginForType()`
   for `SdfUsdaFileFormat`, `SdfUsdcFileFormat`, and `ArDefaultResolver` during
   initialization; if the plugin metadata is not found this is a **`TF_FATAL_ERROR`**
   (process abort), not a soft failure. The wheel must ship `plugInfo.json` +
   schema resources *and* make Plug find them in Pyodide's in-memory filesystem.

Everything else (module list, `__init__.py` generation, `TfScriptModuleLoader`
dependency ordering) already works the same way it does for the native wheel, as
long as (1) and (2) are solved.

---

## 4. Central architecture decision: one shared `libusd_ms.so`

### 4.1 Decision

Build the monolith **once** as a shared Emscripten side module,
`libusd_ms.so` (`-sSIDE_MODULE=1`), vendor it into the wheel's `.libs/`
directory, and have every `_*.so` extension module (`-sSIDE_MODULE=2`,
exporting only its `_PyInit_*`) **dynamically link** against it with an RPATH
that resolves to `.libs/`. This mirrors the native `usd-core` layout
(`libusd_ms` + thin `_*.so` extensions) and is explicitly supported by the
pyemscripten_2026_0 ABI.

This reverses the PR-A choices in `cmake/macros/Public.cmake` and
`cmake/macros/Private.cmake` that force `libType=STATIC`/`usd_m` and
`WHOLE_ARCHIVE`-per-module under `PXR_BUILD_PYODIDE`.

### 4.2 Why this is correct and now feasible

- **pyemscripten_2026_0 explicitly supports vendored shared libs + RPATH.** Per
  the [Pyodide 3.14 ABI docs](https://pyodide.org/en/latest/development/abi/314.html):
  "Other library dependencies should … be built as a shared library and vendored
  into the wheel in a `.libs` directory. Like on native platforms, the RPATH of
  the dependent extension module should also be set…". There is *full RPATH
  support*; `pyodide auditwheel repair` writes the `$ORIGIN`-relative
  `RUNTIME_PATH` into each module's `dylink.0` section.
- **`-sSIDE_MODULE=1` forces whole-archive**, so all `TF_REGISTRY_FUNCTION`
  static-initializer object files (schema/type/plugin registrations, and the
  `TfScriptModuleLoader::RegisterLibrary` entries in generated `moduleDeps.cpp`)
  are retained in `libusd_ms.so`. This is exactly the property PR-A needed
  `WHOLE_ARCHIVE` for — now provided once, centrally.
- **Multi-level side-module dynamic linking works on Emscripten 5.0.3.** The old
  "SIDE_MODULE → SIDE_MODULE" limitation was fixed long ago (≥ 3.1.34); Pyodide
  314 ships Emscripten 5.0.3. Symbols from a globally-loaded dependency are
  visible to dependents.
- **Boost.Python converter registry is shared correctly.** `pxr_boost`'s
  `python` support library is a `pxr_library` (`pxr/external/boost/python/CMakeLists.txt`),
  so under `PXR_BUILD_MONOLITHIC` it becomes an OBJECT lib compiled **into**
  `usd_m`/`usd_ms`. With a single shared `libusd_ms.so`, there is exactly **one**
  Boost.Python to-Python/from-Python converter registry and one `TfType` RTTI
  registry, shared by every extension. (If instead each `_*.so` statically
  embedded its own copy — the PR-A model — cross-module type conversions, e.g.
  passing an `Sdf.Path` into a `UsdGeom` call, would silently fail. Single-module
  `Tf` never exercised this, which is why the PR-A static model appeared to work.)

### 4.3 Why the PR-A blocker no longer applies

`PLAN.md` known blocker #8 records that a separate `libusd_ms.so` SIDE_MODULE
"failed to load under Pyodide 314". That experiment predated the pthread fixes
landed later in PR-A (`-sUSE_PTHREADS=0`, dropping `-pthread` compile flags,
clearing `PXR_THREAD_LIBS`). The most likely original cause was the side module
importing `pthread_*`/shared-memory symbols from `env` that Pyodide's runtime
does not provide. With the thread flags now corrected and `auditwheel repair`
setting RPATH, the shared-module path should load. **This must be re-validated
early (see §11, Task 1) — it is the single highest-risk item in PR-B.**

### 4.4 Fallback ladder if the shared side module still won't load

1. **Preferred:** shared `libusd_ms.so` in `.libs/` + RPATH (this plan).
2. **Diagnostic:** build a 2-module wheel (`Tf` + `Sdf`) against the shared
   `libusd_ms.so` and load in the Node harness to isolate loader/RPATH issues
   before scaling to 30 modules.
3. **Last resort:** keep PR-A's static WHOLE_ARCHIVE model but collapse all
   wrappers into a *single* extension so the monolith is embedded once, then
   re-export submodule namespaces from Python. This is invasive (breaks the
   `_<module>` naming `Tf.PreparePythonModule()` relies on) and is only a
   contingency; document and avoid unless (1) and (2) are proven impossible.

---

## 5. Build-system (CMake) changes

All changes are gated on `EMSCRIPTEN AND PXR_BUILD_PYODIDE` and must not affect
the existing C++ wasm-embed path or native builds.

### 5.1 Build `usd_ms` as a shared side module

In `cmake/macros/Public.cmake` (`pxr_toplevel_prologue`), the current guard
forces the static monolith for Pyodide:

```1201:1207:cmake/macros/Public.cmake
            if(BUILD_SHARED_LIBS AND NOT (EMSCRIPTEN AND PXR_BUILD_PYODIDE))
                set(libType SHARED)
                set(libName "usd_ms")
            else()
                set(libType STATIC)
                set(libName "usd_m")
            endif()
```

Change so that, under Pyodide, we build the **shared** `usd_ms` (which already
gets `-sSIDE_MODULE=1` from the adjacent block at lines 1220-1223). Net effect:
`libType=SHARED`, `libName=usd_ms`, `-sSIDE_MODULE=1`. Confirm the
`pxr_toplevel_epilogue` `target_link_libraries(usd_m …)` block (currently
skipped for Pyodide) is **re-enabled** so all `PXR_OBJECT_LIBS` are linked into
the shared monolith.

### 5.2 Link extensions dynamically (drop per-module WHOLE_ARCHIVE)

In `cmake/macros/Private.cmake` (`_pxr_target_link_libraries`), the current guard
routes Pyodide through the static WHOLE_ARCHIVE branch:

```870:876:cmake/macros/Private.cmake
            if(BUILD_SHARED_LIBS AND NOT (EMSCRIPTEN AND PXR_BUILD_PYODIDE))
                set(internal usd_m)
            else()
                set(internal "$<LINK_LIBRARY:WHOLE_ARCHIVE,usd_m>")
            endif()
```

Change so Pyodide takes the `set(internal usd_ms)` shared path: each `_*.so`
gets `usd_ms` as a normal shared dependency (undefined USD symbols resolved at
load time from `libusd_ms.so`). `PXR_PY_UNDEFINED_DYNAMIC_LOOKUP=ON` already
permits unresolved symbols at link time for the extension modules.

### 5.3 Do not embed resources for Pyodide side modules

`_install_resource_files()` adds `--embed-file` link options under `EMSCRIPTEN`:

```335:351:cmake/macros/Private.cmake
        if (EMSCRIPTEN)
            …
            target_link_options(${NAME} PUBLIC
                "$<BUILD_INTERFACE:SHELL:--embed-file …>"
                "$<INSTALL_INTERFACE:SHELL:--embed-file …>")
        endif()
```

`--embed-file` targets the Emscripten JS loader's virtual FS, which is how the
C++ `wasmFetchResolver` MAIN_MODULE consumes plugInfo. Pyodide loads side
modules as raw wasm through its own loader and does **not** honor per-module
`--embed-file` data. Embedding would also bloat `libusd_ms.so`. **Gate this
block to `EMSCRIPTEN AND NOT PXR_BUILD_PYODIDE`.** For Pyodide, rely on the
normal `install(FILES …)` step (kept) + shipping those installed files as wheel
package data (§6) discovered via a runtime plugin path (§7).

### 5.4 Emit the top-level `pxr/__init__.py`

`pxr_setup_python()` already writes `__init__.py` with
`__all__ = [<PXR_PYTHON_MODULES>]` from the global module list. This works
unchanged for Pyodide; the packaging script (§6) appends the plugin-path
bootstrap (§7) to the installed copy, analogous to the Windows DLL-path append
in `build_scripts/pypi/package_files/setup.py`.

### 5.5 Optional linker size/robustness flags for `usd_ms`

Consider adding, for the Pyodide `usd_ms` link only:
`-sALLOW_MEMORY_GROWTH=1` (already global), and evaluate `-O2`/`-Oz` +
`wasm-opt` for size in PR-C. Not required for correctness in PR-B.

---

## 6. Module set and install → wheel layout

### 6.1 Modules to ship (matches PyPI `usd-core`, no imaging)

**Base (`pxr/base/`):** `Tf`, `Gf`, `Vt`, `Ts`, `Trace`, `Work`, `Plug`
(`arch`, `js`, `pegtl` are C++-only, no `_*.so`).

**USD (`pxr/usd/`):** `Ar`, `Kind`, `Sdf`, `Sdr`, `Pcp`, `Usd`, `UsdGeom`,
`UsdVol`, `UsdMedia`, `UsdShade`, `UsdLod`, `UsdLux`, `UsdProc`, `UsdProfiles`,
`UsdRender`, `UsdHydra`, `UsdRi`, `UsdSemantics`, `UsdSkel`, `UsdUI`, `UsdUtils`,
`UsdPhysics`.

**Validation (`pxr/usdValidation/`):** `UsdValidation` (the sibling
`usd*Validators` are C++/plugInfo-only, no `_*.so`).

≈ **30 extension modules.** Excluded by the existing configure flags:
all `pxr/imaging` + `pxr/usdImaging` (imaging), `pxr/exec` (exec), `usdMtlx`
(MaterialX), `usdAbc`/`usdDraco` (optional plugins). `usdShaders` is a C++
`pxr_plugin` (no `_*.so`) but its `plugInfo.json` + `shaders/*` resources must
still ship for `Sdr`.

### 6.2 Native install tree (from `cmake --install`)

```
inst/
├── lib/
│   ├── libusd_ms.so                      # shared side module (SIDE_MODULE=1)
│   ├── python/pxr/
│   │   ├── __init__.py                    # __all__ = [...]
│   │   ├── Tf/{__init__.py,_tf.so}
│   │   ├── Usd/{__init__.py,_usd.so, usdGenSchema.py, codegenTemplates/…}
│   │   └── … (all modules)
│   └── usd/                               # plugInfo aggregator + per-lib resources
│       ├── plugInfo.json                  # {"Includes":["*/resources/"]}
│       ├── sdf/resources/plugInfo.json
│       ├── usdGeom/resources/{plugInfo.json,generatedSchema.usda,usdGeom/schema.usda}
│       └── … (all schema + resource dirs)
└── plugin/
    └── usd/
        ├── plugInfo.json
        └── usdShaders/resources/{plugInfo.json,shaders/*.usda,*.glslfx}
```

### 6.3 Wheel layout (after repackage + `auditwheel repair`)

Mirror the PyPI relocation (`build_scripts/pypi/package_files/setup.py`):

```
usd_core-<ver>-cp314-cp314-pyemscripten_2026_0_wasm32.whl
└── pxr/
    ├── __init__.py                # __all__ + plugin-path bootstrap (§7)
    ├── pluginfo/                  # was inst/lib/usd + inst/plugin/usd
    │   ├── plugInfo.json
    │   ├── sdf/resources/…
    │   ├── usdGeom/resources/…
    │   ├── usdShaders/resources/…
    │   └── …
    ├── Tf/{__init__.py,_tf.so}
    ├── Usd/{__init__.py,_usd.so,usdGenSchema.py,codegenTemplates/…}
    ├── … (all modules)
    └── .libs/
        └── libusd_ms.so           # vendored by auditwheel repair; extensions RPATH here
```

Package the wheel with `usd-core` naming to keep parity with the PyPI wheel and
the plan's eventual `packages="usd-core"` path.

---

## 7. Runtime plugin discovery in the browser

### 7.1 The mechanism

`Plug_InitConfig` (`pxr/base/plug/initConfig.cpp`) runs as an `ARCH_CONSTRUCTOR`
when `libusd_ms.so` is loaded. It builds the plugin search path from, in order:
the `PXR_PLUGINPATH_NAME` env var, the compile-time `PXR_BUILD_LOCATION` (`usd`),
`PXR_PLUGIN_BUILD_LOCATION` (`../plugin/usd`), and (if defined)
`PXR_INSTALL_LOCATION`. Relative paths are anchored to the directory of the Plug
binary via `ArchGetAddressInfo`, falling back to `ArchGetExecutablePath()` when
that fails (the likely case under a wasm side module).

Because relative anchoring is unreliable in Pyodide's MEMFS, the robust approach
is an **absolute** `PXR_PLUGINPATH_NAME` pointing at the installed
`pxr/pluginfo/`.

### 7.2 The bootstrap (set env var before first extension import)

Key ordering fact: `import pxr` runs only the lightweight top-level
`pxr/__init__.py` (sets `__all__`); **no** `.so` loads yet. The first
`from pxr import Tf` (or any module) triggers `Tf.PreparePythonModule()` →
`import _tf` → the loader pulls the `libusd_ms.so` dependency → `Plug_InitConfig`
runs. So the env var must be set **inside the top-level `pxr/__init__.py`**,
before any submodule import.

Append to the installed `pxr/__init__.py` (done by the packaging script, §6/§8):

```python
# Pyodide: point Plug at the vendored pluginfo before any extension loads.
import os as _os
_pluginfo = _os.path.join(_os.path.dirname(_os.path.realpath(__file__)), "pluginfo")
_existing = _os.environ.get("PXR_PLUGINPATH_NAME", "")
_os.environ["PXR_PLUGINPATH_NAME"] = (
    _pluginfo + (_os.pathsep + _existing if _existing else "")
)
del _os, _pluginfo, _existing
```

Python's `os.environ` assignment calls `putenv`/`setenv`, so the C++
`TfGetenv("PXR_PLUGINPATH_NAME")` in `Plug_InitConfig` sees it. The aggregator
`pluginfo/plugInfo.json` (`{"Includes":["*/resources/"]}`) then pulls every
per-library plugInfo recursively.

### 7.3 Belt-and-braces: bake `PXR_INSTALL_LOCATION`

Also configure with `-DPXR_INSTALL_LOCATION=../pxr/pluginfo` (as PyPI does) so
there is a compile-time fallback if the env var path is ever wrong. Keep the env
var as the primary mechanism.

### 7.4 `LibraryPath` rewriting

For the monolithic core libraries the substituted `LibraryPath` is empty (see
`_plugInfo_subst`/`Private.cmake`), so there is **no** dlopen at plugin-load time
— the code is already in `libusd_ms.so`. Therefore the native
`build_scripts/pypi/updatePluginfos.py` `LibraryPath` rewrite is largely a no-op
here. Verify the `usdShaders` plugInfo (`ShaderResources: "shaders"`,
`LibraryPath` empty for the monolithic plugin) resolves its shader resource dir
relative to `pluginfo/usdShaders/resources/`. Add a minimal rewrite only if a
non-empty `LibraryPath` survives substitution.

---

## 8. Packaging script: `build_scripts/pyodide/package_wheel.py`

Generalize `package_tf_spike_wheel.py` (single `_tf.so`) into a full packager.
Responsibilities:

1. **Install** — run `cmake --install <usd-build> --prefix <inst>` (build driver
   builds `install` target instead of `--build-target _tf`).
2. **Relocate** — copy `inst/lib/python/pxr` → staging; move `inst/lib/usd` and
   `inst/plugin/usd/*` into `pxr/pluginfo/` (reuse the logic in
   `build_scripts/pypi/package_files/setup.py`, adapted for a single
   monolithic side module and no Windows branch).
3. **Place the monolith** — copy `inst/lib/libusd_ms.so` where `auditwheel
   repair` can find and vendor it (or pre-stage into `pxr/.libs/`).
4. **Generate `setup.py`** — reuse the `EmscriptenBdistWheel.get_tag()` →
   `("cp314","cp314","pyemscripten_2026_0_wasm32")` trick from
   `wheel_staging/setup.py`; set `name="usd-core"`, `package_data` to include
   `*.so`, `pxr/pluginfo/**`, and pure-Python companions (`usdGenSchema.py`,
   `codegenTemplates/**`, `UsdUtils/*.py`, etc.).
5. **Append plugin-path bootstrap** to the staged `pxr/__init__.py` (§7.2).
6. **`bdist_wheel`** then **`pyodide auditwheel repair --libdir <inst/lib>`** to
   vendor `libusd_ms.so` into `.libs/` and write RPATH into every `_*.so`'s
   `dylink.0` section. Tolerate the known non-zero-exit-but-wheel-written case
   already handled in the PR-A packager.
7. Emit the final `usd_core-*.whl` into `dist/pyodide/`.

Keep `--build-root`, `--output-dir`, `--version` args; add `--skip-build` to
repackage an existing install tree during iteration.

### 8.1 Build driver changes (`build_spike.py` → keep or add `build_usd.py`)

Minimal changes: allow `--build-target install` (or a new `build_usd.py` that
calls the same configure and then `cmake --build --target install`). The
existing configure flags are already correct for the full `usd-core` set. Keep
`--skip-onetbb` and the oneTBB build. Confirm the whole graph compiles under
Emscripten (some libraries beyond Tf may surface additional wasm32 ABI issues
similar to the `TfPyObjWrapper` fix — see §10 risks).

---

## 9. Testing strategy

### 9.1 Node smoke test (CI-able, no browser)

Add `build_scripts/pyodide/test_usd_import.mjs` (extends `test_tf_import.mjs`):
serve the wheel over `http.server`, `micropip.install`, then run a Python
snippet that exercises the plugin registry and cross-module type flow:

```python
from pxr import Usd, UsdGeom, Sdf, Gf
stage = Usd.Stage.CreateInMemory()          # exercises Sdf usda file format plugin
world = UsdGeom.Xform.Define(stage, "/World")
cube = UsdGeom.Cube.Define(stage, "/World/Cube")
cube.GetSizeAttr().Set(2.0)
stage.SetDefaultPrim(world.GetPrim())
usda = stage.GetRootLayer().ExportToString()  # serialize round-trip
assert "def Cube" in usda
```

Success criteria: no `TF_FATAL_ERROR` from `DemandPluginForType`, correct
serialized output, and a cross-module call (`Sdf.Path`/`Gf.Vec` into `UsdGeom`)
that proves the shared Boost.Python registry.

Stage the test incrementally: first `Tf`+`Sdf` (validates shared side module +
plugin path), then the full set.

### 9.2 Browser demo

Update `extras/pyodide/demo/`:
- `usd_demo.py` — the guided script from `PLAN.md` (`Usd`, `UsdGeom` authoring).
- `bootstrap.py` — micropip-install the co-hosted `usd_core-*.whl` (generalize
  the existing glob from `usd_tf_pyodide_spike-*` to `usd_core-*`).
- `index.html` — point `replay-src` at `usd_demo.py`; keep the pyrepl-web
  `grill` `pyrepl.js` script tag.
- `README.md` — update build/package/serve steps for the full wheel.

Manual browser validation requires the pyrepl-web `grill` sibling clone (built
with `bun run build`) as documented; the Node harness is the automated gate.

---

## 10. Risks and mitigations

| # | Risk | Likelihood | Mitigation |
|---|------|-----------|------------|
| 1 | Shared `libusd_ms.so` side module still fails to load (blocker #8 regression) | Med | Validate with a 2-module wheel first (§4.4); inspect `dylink.0`/imports with `pyodide auditwheel show`; ensure no `pthread_*`/`env` imports remain |
| 2 | RPATH not resolving `.libs/libusd_ms.so` | Med | Use `pyodide auditwheel repair` (writes `$ORIGIN` RUNTIME_PATH); verify with `auditwheel show`; confirm loader pulls dep before `_*.so` init |
| 3 | plugInfo not found → `TF_FATAL_ERROR` at `Sdf`/`Ar` init | Med | Set absolute `PXR_PLUGINPATH_NAME` in top-level `__init__.py` before first import (§7.2); bake `PXR_INSTALL_LOCATION` fallback; test via `TF_DEBUG=PLUG_INFO_SEARCH` in Node |
| 4 | Cross-module type conversion breaks (duplicated Boost.Python/TfType registries) | Low (with shared monolith) | Single `libusd_ms.so` guarantees one registry; assert cross-module call in smoke test (§9.1) |
| 5 | Additional wasm32 ABI mismatches in non-Tf libraries (like `TfPyObjWrapper`) | Med | Build full graph early; fix per-type stub sizes/alignments as they surface; keep fixes `#if defined(__EMSCRIPTEN__) && defined(__wasm32__)` guarded |
| 6 | Wheel size (tens of MB) hurts browser load | High (size) / Low (correctness) | Acceptable for PR-B; defer `-Oz`/`wasm-opt`/compression to PR-C; note it |
| 7 | `os.environ` → C `getenv` propagation timing | Low | Set env var in top-level `__init__.py` (runs before any `.so`); covered by smoke test |
| 8 | `--embed-file` path accidentally active for Pyodide | Low | Explicitly gate §5.3; verify `libusd_ms.so` has no embedded FS payload |

---

## 11. Implementation task breakdown (ordered)

Each task should be its own commit; validate the risky ones before scaling up.

1. **De-risk the shared side module.** CMake changes §5.1–§5.2 (+ §5.3 gate).
   Build `usd_ms` + `_tf` + `_sdf`. Package a 2-module wheel with `auditwheel
   repair`. Load in the Node harness. **Gate:** `from pxr import Sdf;
   Sdf.Layer.CreateAnonymous()` works (proves shared monolith + RPATH + plugin
   path). *This is the make-or-break task.*
2. **Runtime plugin discovery.** Implement §7 (`pxr/__init__.py` bootstrap +
   `PXR_INSTALL_LOCATION`). Verify no `DemandPluginForType` fatal via
   `TF_DEBUG=PLUG_INFO_SEARCH`.
3. **Full build/install driver.** §8.1 — build the `install` target; fix any
   wasm32 ABI issues that surface across the full module graph (§10 risk 5).
4. **Full packager `package_wheel.py`.** §8 — relocation, pluginfo staging,
   companions, `auditwheel repair`, `usd-core` naming.
5. **Full Node smoke test.** §9.1 `test_usd_import.mjs` across all modules with
   authoring + serialization round-trip.
6. **Browser demo.** §9.2 — `usd_demo.py`, `bootstrap.py`, `index.html`,
   `README.md`.
7. **Docs.** Update `PLAN.md` PR-B checkboxes; fold resolved items out of "Known
   blockers"; document the shared-monolith model as the decided layout.

---

## 12. Environment / toolchain notes

PR-B build+test requires the Pyodide 314 cross-build toolchain, which is a large
download not present in a fresh agent VM:

```bash
pip install 'pyodide-build>=0.36' jinja2 wheel
pyodide xbuildenv install 314.0.2 --force && pyodide xbuildenv use 314.0.2
pyodide xbuildenv install-emscripten          # Emscripten 5.0.3
cd build_scripts/pyodide && npm install       # pyodide (Node) for the smoke test
```

Because this setup (pyodide-build, Emscripten xbuildenv, oneTBB build, Node
`pyodide` package) is heavy and shared by any agent iterating on this work, it
should be encoded into the Cloud Agent environment config (via an env-setup
agent at cursor.com/onboard) so subsequent runs skip re-downloading the
toolchain.

---

## 13. Definition of done for PR-B

- `usd_core-<ver>-cp314-cp314-pyemscripten_2026_0_wasm32.whl` builds from a
  single command chain (build → install → `package_wheel.py`).
- Node harness: `from pxr import Usd, UsdGeom, Sdf, Gf` + author/serialize
  round-trip passes with no fatal plugin errors.
- Browser demo runs `usd_demo.py` under pyrepl-web `grill` and prints stage
  contents.
- The wheel ships the C++ core **once** (`.libs/libusd_ms.so`) with thin `_*.so`
  extensions, plus `pxr/pluginfo/`.
- `PLAN.md` PR-B section updated to reflect the shared-monolith decision.
