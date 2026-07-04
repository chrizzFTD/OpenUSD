# PR-C — CI, size hardening, and PyPI release as `grill-usd-core`

**Status:** implemented up to the publish step (§11 tasks 1–5, 8 done; §11
tasks 6–7 need maintainer account access — see the runbook in §4.4)
**Branch base:** builds on PR-B (`cursor/pyodide-pr-b-usd-core-*`, shared
`libusd_ms.so` side module + `package_wheel.py` + browser demo)
**Scope:** all work stays in this OpenUSD fork; consume
[chrizzFTD/pyrepl-web `grill`](https://github.com/chrizzFTD/pyrepl-web/tree/grill)
as a read-only Pyodide 314 runtime.

This document is the deep architecture/design analysis and step-by-step
implementation plan for PR-C, building on the PR-A spike and the PR-B full
`usd-core` wheel. It complements [`PLAN.md`](./PLAN.md) (roadmap) and
[`PR-B-PLAN.md`](./PR-B-PLAN.md) (the shared-monolith design that PR-C ships).
Read those first for context.

---

## 1. Goal recap

PR-A proved a single `Tf` module loads under Pyodide 314. PR-B built the full
`usd-core` module set as one shared `libusd_ms.so` side module (`-sSIDE_MODULE=1`)
vendored in the wheel's `.libs/`, with ~29 thin `_*.so` extensions
(`-sSIDE_MODULE=2`) and a `pxr/pluginfo/` registry, validated by a Node harness
and an in-browser pyrepl-web demo. The wheel is built locally by
`build_scripts/pyodide/{build_spike,package_wheel}.py` and is **not** committed.

PR-C turns that one-off local artifact into a **published, reproducible,
CI-built package on PyPI** so browser consumers can
`micropip.install("grill-usd-core")` (and use `<py-repl packages="grill-usd-core">`)
without hand-hosting the wheel, plus the size/robustness hardening deferred from
PR-B (`PR-B-PLAN.md` §5.5, risk #6).

Concretely, PR-C must:

1. **Publish** a `grill-usd-core` wheel to PyPI (PEP 783 `pyemscripten_2026_0_wasm32`).
2. **Automate** the build → package → smoke-test → publish flow in GitHub Actions.
3. **Harden**: shrink the wheel (`-Oz`/`wasm-opt`), enrich metadata, and add a
   `pyodide venv` pip-install smoke test alongside the Node harness.
4. **Repoint** the demo/docs at the published package as the canonical install
   path (keeping the local-wheel path for development).

---

## 2. What PR-B already gives us (and its learnings)

| Area | PR-B artifact | PR-C impact |
|------|---------------|-------------|
| Build driver | `build_spike.py --build-target install` (oneTBB + configure + install) | wrap in a CI script; consider `-Oz` |
| Packager | `package_wheel.py` (relocate `pxr`, stage `pxr/pluginfo/`, `auditwheel repair`, `name="usd-core"`) | parameterize `--dist-name`; enrich metadata; add size passes |
| Wheel | `usd_core-26.8-cp314-cp314-pyemscripten_2026_0_wasm32.whl`, ~12 MB (libusd_ms.so ~30 MB uncompressed) | rename → `grill_usd_core-*`; shrink |
| Node test | `test_usd_import.mjs` (author + serialize round-trip) | reuse in CI |
| Demo | `extras/pyodide/demo/` (local wheel via `packages="./…whl"`) | add `packages="grill-usd-core"` path |

Key learnings from PR-B that shape PR-C:

- **The wheel already uses the PyPI-accepted tag.** PR-B emits
  `pyemscripten_2026_0_wasm32`, which is exactly the PEP 783 platform tag PyPI
  now accepts (see §4). No tag change is required — only metadata and naming.
- **Import name is `pxr`, independent of the distribution name.** The plugin
  bootstrap in `pxr/__init__.py` resolves `pluginfo` relative to `pxr/__file__`,
  so renaming the *distribution* to `grill-usd-core` does not touch any Python
  or C++ path logic.
- **`auditwheel repair` derives the vendored dir from the distribution name.**
  Today that is `usd_core.libs/`; after the rename it becomes
  `grill_usd_core.libs/`. Pyodide's loader discovers vendored libs generically
  (it does not hardcode `usd_core.libs`), so this should be transparent — but it
  **must be re-validated end-to-end** (§10 R1), since dynamic-library discovery
  was the single hardest part of PR-B.
- **Metadata is currently minimal** (`Name`, `Version`, `Summary`,
  `Requires-Python` only). PyPI/`twine check` need license, long description,
  classifiers, and URLs (§4.2).
- **Build is `Release` (`-O3`).** Pyodide's default `-Oz` is overridden by
  CMake's `Release` flags, so the wheel is larger than necessary (§6).

---

## 3. Package identity: `grill-usd-core`

### 3.1 Naming rationale

Publish under **`grill-usd-core`**, distinct from PyPI's official
[`usd-core`](https://pypi.org/project/usd-core/) (which has **no** wasm support).
Rationale:

- **Avoids confusion / squatting concerns.** `usd-core` is Pixar's; this is an
  unofficial, experimental WebAssembly build. A separate name prevents anyone
  from mistaking it for the official package and avoids any claim on the
  `usd-core` project namespace.
- **Namespaces it under the `grill` project** (the pyrepl-web `grill` runtime /
  chrizzFTD tooling that consumes it), signalling it is the *testing* package
  for the Pyodide/wasm build.
- **Coexists cleanly** with the official `usd-core` on PyPI as an independent
  project.

### 3.2 Distribution name vs import name

- **Distribution (PyPI) name:** `grill-usd-core` (normalized: `grill_usd_core`).
- **Import name:** unchanged — `pxr` (`from pxr import Usd, …`). This mirrors
  `usd-core`'s own dist-name ≠ import-name split and keeps every existing script
  and the demo Python untouched.
- **Caveat:** because the import name is `pxr`, `grill-usd-core` and the official
  `usd-core` cannot be installed into the *same* environment (both own `pxr`).
  This is a non-issue in practice — `usd-core` has no `pyemscripten` wheel, so it
  cannot be installed in Pyodide anyway. Document it in the README.

### 3.3 Wheel filename and `.libs` directory

After the rename, the artifacts become:

```
grill_usd_core-<ver>-cp314-cp314-pyemscripten_2026_0_wasm32.whl
└── grill_usd_core.libs/libusd_ms.so    # was usd_core.libs/
```

`package_wheel.py` gains a `--dist-name` argument (default `grill-usd-core`; keep
`usd-core` available for local parity testing). The demo's wheel glob and the
`packages=` attribute update accordingly (§9).

### 3.4 Versioning scheme

`usd-core` versions as `<MINOR>.<PATCH>` from `pxr.h` (e.g. `26.8`). For a
testing package published repeatedly against the same USD version and possibly
multiple Pyodide/Emscripten ABIs, adopt a **PEP 440** scheme that keeps parity
with USD while allowing rebuilds:

- **Primary:** mirror the USD version — `grill-usd-core==26.8`.
- **Rebuilds of the same USD version** (packaging fixes, size passes, new ABI
  builds): use a `.postN` segment — `26.8.post1`, `26.8.post2`. PyPI files are
  immutable, so every re-publish needs a new version.
- **Pre-release iteration:** use `.devN` / `aN` (e.g. `26.8.dev0`) on **TestPyPI**
  first; promote a clean version to PyPI.
- Do **not** encode the ABI in the version (it lives in the wheel tag). If a
  second ABI (e.g. `pyemscripten_2027_0` for Python 3.15) is ever built, publish
  it as an additional wheel file under the *same* version.

Derive the version in `package_wheel.py` from `pxr.h` (already done) plus an
optional `--post`/`--version` override for `.postN`/`.devN`.

---

## 4. PyPI publishing feasibility (PEP 783)

### 4.1 Platform tag acceptance — confirmed

[PEP 783 (Emscripten Packaging)](https://peps.python.org/pep-0783/) was accepted
and PyPI/warehouse merged support on 2026-04-21
([pypi/warehouse#19804](https://github.com/pypi/warehouse/pull/19804)); `packaging`
26.1 ships the tag. Package indexes accept any wheel whose platform tag matches
`pyemscripten_[0-9]+_[0-9]+_wasm32`. **Our wheel already emits
`pyemscripten_2026_0_wasm32`**, so no tag work is needed. (The older `pyodide_*`
tag is deprecated for PyPI uploads.)

Per the [Pyodide 314 ABI docs](https://pyodide.org/en/stable/development/abi.html),
`pyemscripten_2026_0` corresponds to Python 3.14 / Pyodide 314.x.

### 4.2 Required metadata & classifiers

The current wheel METADATA is too thin for a good PyPI listing and to pass
`twine check`. `package_wheel.py`'s generated `setup.py` must add:

- `long_description` + `long_description_content_type="text/markdown"` from a
  dedicated PyPI README (see §9) that states this is an **unofficial, experimental
  WebAssembly/Pyodide build of OpenUSD**, not affiliated with Pixar and not the
  official `usd-core`.
- `license` — OpenUSD's terms (`LicenseRef-TOST-1.0`, matching `usd-core`), and
  ship `LICENSE.txt` in the wheel.
- `classifiers` including the PEP 783-recommended
  **`Environment :: WebAssembly :: Emscripten`**, plus
  `Programming Language :: Python :: 3.14`,
  `Topic :: Multimedia :: Graphics :: 3D Modeling`,
  `Intended Audience :: Developers`,
  `Development Status :: 3 - Alpha` (it is a testing package).
- `project_urls` (Source → this fork, the PR-B/PR-C plan docs, the demo).
- Keep `Requires-Python: >=3.14, <3.15`.
- `author`/`maintainer` for the fork.

Publish **wheel-only** (no sdist): an sdist is meaningless here because building
from source requires the full USD + oneTBB + Emscripten cross toolchain, not a
`pip install` build. PyPI accepts wheel-only projects.

### 4.3 Consumption via micropip / `packages=`

Once on PyPI (default index `https://pypi.org/simple`), consumers can:

```python
import micropip
await micropip.install("grill-usd-core")   # resolves the pyemscripten wheel
```

and the demo can use `<py-repl packages="grill-usd-core">` — pyrepl `await`s
`micropip.install(packages)` before the REPL/replay (the PR-B timing fix still
applies). `micropip` ≥ the version bundled in Pyodide 314 accepts `pyemscripten`
wheels (micropip #270). `grill-usd-core` has **no** Python dependencies (the C++
core is self-contained in `libusd_ms.so`), so dependency resolution is trivial
and offline-friendly.

Fallbacks retained for development / pre-publish:
- Direct URL: `micropip.install("https://…/grill_usd_core-*.whl")`.
- Local co-hosted wheel: `packages="./grill_usd_core-*.whl"` (PR-B demo path).
- Custom index (TestPyPI): `micropip.install("grill-usd-core", index_urls=[…])`.

### 4.4 TestPyPI + Trusted Publishing

- **Dry-run on TestPyPI** first (`https://test.pypi.org`) using `.devN` versions,
  and validate a real Pyodide install against it via `index_urls`.
- **Publish with PyPI Trusted Publishing (OIDC)** from GitHub Actions — no
  long-lived API token in the repo. Configure a trusted publisher on the PyPI
  `grill-usd-core` project pointing at this repo + the release workflow.
- **Claim the name** `grill-usd-core` on PyPI (and TestPyPI) before the first
  automated run.

#### Maintainer release runbook (as implemented — needs account access)

Everything below is wired up in `.github/workflows/pyodide-wheel.yml`; only
these one-time account steps and the workflow dispatches need the maintainer:

1. On **TestPyPI** (test.pypi.org) *and* **PyPI** (pypi.org): add a **pending
   trusted publisher** for the project name `grill-usd-core` (Your account →
   Publishing), with repository `chrizzFTD/OpenUSD`, workflow
   `pyodide-wheel.yml`, and environment `testpypi` / `pypi` respectively.
   The first successful OIDC upload claims the name.
2. In the GitHub repo settings, create the `testpypi` and `pypi`
   **environments** (optionally with required reviewers to gate publishes).
3. **TestPyPI dry-run**: run the *Pyodide wheel (grill-usd-core)* workflow
   with `publish: testpypi` and `version: 26.8.dev2` (bump `.devN` per
   iteration — (Test)PyPI files are immutable). Validate the published
   package end-to-end:
   `node build_scripts/pyodide/test_usd_import.mjs grill-usd-core
   https://test.pypi.org/simple`.

   > **Done for `26.8.dev1`** (2026-07-04, via a maintainer TestPyPI API
   > token instead of the workflow):
   > [test.pypi.org/project/grill-usd-core/26.8.dev1](https://test.pypi.org/project/grill-usd-core/26.8.dev1/)
   > — validated with the Node harness resolving from
   > `https://test.pypi.org/simple` (install + author + serialize
   > round-trip) and a `pyodide venv` `pip install --index-url
   > https://test.pypi.org/simple grill-usd-core==26.8.dev1`. The
   > `grill-usd-core` name is now claimed on TestPyPI by the maintainer
   > account, so the TestPyPI trusted publisher must be added on the
   > *project* (Manage → Publishing), not as a pending publisher.
4. **PyPI release**: dispatch with `publish: pypi` (no version override →
   `26.8` from `pxr.h`), or push a `pyodide-v*` tag. Re-publishes of the same
   USD version use the `post` input (`26.8.postN`).

   > **Done for `26.8`** (2026-07-04, via a maintainer PyPI API token — the
   > same locally built + fully validated wheel as the TestPyPI dry-run):
   > [pypi.org/project/grill-usd-core/26.8](https://pypi.org/project/grill-usd-core/26.8/).
   > The name is claimed on PyPI too, so the trusted publisher is likewise
   > added on the *project* (Manage → Publishing). Future releases (e.g.
   > `26.8.postN`, next USD versions) should go through the workflow.
5. Validate: `node build_scripts/pyodide/test_usd_import.mjs grill-usd-core`
   and the browser demo (`extras/pyodide/demo/`, `packages="grill-usd-core"`).

   > **Done for `26.8`**: Node harness installing by bare name from the
   > default index (micropip resolution + author/serialize round-trip),
   > `pyodide venv` `pip install grill-usd-core`, and the browser demo with
   > `packages="grill-usd-core"` all pass against the live PyPI package.

---

## 5. Packaging changes (`build_scripts/pyodide/package_wheel.py`)

Incremental changes on top of PR-B's packager:

1. **`--dist-name` argument** (default `grill-usd-core`). Drives `name=` and,
   implicitly, the `*.libs` dir. Keep `usd-core` selectable for local parity.
2. **Rich metadata** (§4.2): `long_description` from a PyPI README, `license`
   + bundled `LICENSE.txt`, `classifiers` (incl. `Environment :: WebAssembly ::
   Emscripten`), `project_urls`, author. Ensure `twine check` passes.
3. **Version handling**: keep `pxr.h` detection; add `--post N` (→ `X.Y.postN`)
   and honor `--version` for `.devN`/`aN`.
4. **Size passes** (§6): optional `wasm-opt -Oz` over `libusd_ms.so` (and the
   `_*.so`) before/after `auditwheel repair`; verify the module still loads.
5. **`twine check`** step on the produced wheel; fail packaging on error.
6. Keep the existing relocation, `pxr/pluginfo/` staging, `pxr/__init__.py`
   plugin bootstrap, and `auditwheel repair` (tolerating the known non-zero
   introspection exit).

---

## 6. Size hardening (deferred from PR-B §5.5 / risk #6)

Current: `libusd_ms.so` ≈ 30 MB uncompressed, wheel ≈ 12 MB compressed, built at
`-O3` (CMake `Release` overrides Pyodide's default `-Oz`). Levers, in rough
order of value/effort:

1. **Optimize for size.** Build the Pyodide config with `-Oz` (or CMake
   `MinSizeRel`) for `libusd_ms.so`; measure load-time impact. This is the
   biggest, cheapest win and is likely to roughly halve the code size vs `-O3`.
2. **`wasm-opt -Oz` (Binaryen)** as a post-link pass on `libusd_ms.so` (and
   optionally the wrappers). Emscripten runs some of this, but an explicit `-Oz`
   pass plus `--strip-debug`/`--strip-producers` typically shaves more.
3. **Strip.** Ensure `-g0` and no debug/DWARF in the shipped `.so` (Pyodide
   config already sets `-g0`; confirm our explicit flags do not re-add `-g`).
4. **Dead-code / feature trims.** `-sSTRICT`, drop unused Emscripten runtime
   features; confirm `-sALLOW_MEMORY_GROWTH` and exception/longjmp flags stay.
5. **Transport compression.** Serve the wheel and `.so` with `Content-Encoding:
   gzip`/`br`; micropip/pyodide fetch honors it. This is a *hosting* win (demo
   `server.py` + any CDN), independent of the wheel bytes on PyPI.
6. **Module-set trimming (optional, future).** Splitting rarely-used schema
   modules into a separate wheel conflicts with `usd-core` parity (PR-B DoD);
   keep parity for `grill-usd-core` and defer any split to a later PR.

Target: a meaningful reduction (aim to bring the wheel comfortably under
PR-B's ~12 MB, ideally toward single-digit MB) **without** regressing the Node
or browser round-trip. Every size pass must be gated behind a re-run of the
smoke tests.

Note the ceiling is fine for PyPI regardless: the per-file limit is 100 MB and
we are well under it.

### 6.1 As-implemented measurements

Both levers were built and measured end-to-end (full monolith rebuilds, gated
by the Node + `pyodide venv` smoke tests):

| Build | `libusd_ms.so` | wheel (compressed) |
|-------|---------------:|-------------------:|
| PR-B parity: `-O3`, no post-link pass | 29,967,509 B | 11,905,169 B |
| `MinSizeRel` (`-Oz`) compile + `wasm-opt -Oz` | 34,405,358 → 32,093,614 B | 15,344,457 B |
| **Shipped: `-O3` + `wasm-opt -Oz` + strip** | **29,994,772 → 27,490,863 B (−8.3%)** | **11,790,256 B** |

Counter-intuitively the `-Oz` *compile* is ~15% **larger** than `-O3` for this
codebase (USD's heavily templated code shrinks more from `-O3`'s aggressive
inlining + GVN than from `-Oz`'s size heuristics), so `Release` stays the
default (`build_spike.py --build-type` keeps `MinSizeRel` selectable for
re-measurement). The shipped win is the post-link `wasm-opt -Oz
--strip-debug --strip-producers` pass in `package_wheel.py` (skippable via
`--no-wasm-opt`): −8.3% on the uncompressed monolith the browser must
instantiate (a second `wasm-opt` pass and strip-only were measured; both
negligible). The compressed wheel only shrinks ~1% (wasm compresses well);
transport compression (§6 item 5) remains the hosting-side lever.

---

## 7. CI — GitHub Actions

The heart of PR-C (original `PLAN.md` PR-C bullet). A single workflow, e.g.
`.github/workflows/pyodide-wheel.yml`:

**Triggers:** `workflow_dispatch` (manual, with a `publish: testpypi|pypi|none`
input) and `push` tags matching `pyodide-v*` (release).

**Job `build` (ubuntu-latest):**
1. Checkout.
2. Install host deps: `pip install 'pyodide-build>=0.36' jinja2 wheel twine`.
3. `pyodide xbuildenv install 314.0.2 --force && pyodide xbuildenv use 314.0.2 &&
   pyodide xbuildenv install-emscripten`.
4. **Cache** `~/.cache/pyodide-build` (xbuildenv + emsdk) and the oneTBB build
   (`build/pyodide-spike/tbb`) keyed on the pinned versions — the USD monolith
   compile is the long pole (~10 min); caching TBB + xbuildenv avoids re-downloads.
5. `python build_scripts/pyodide/build_spike.py --build-target install`
   (first run builds oneTBB; subsequent use `--skip-onetbb`).
6. `python build_scripts/pyodide/package_wheel.py --dist-name grill-usd-core
   [--post N]` → `dist/pyodide/grill_usd_core-*.whl`.
7. `twine check dist/pyodide/*.whl`.
8. **Node smoke test:** `cd build_scripts/pyodide && npm ci && node
   test_usd_import.mjs ../../dist/pyodide/grill_usd_core-*.whl`.
9. **`pyodide venv` smoke test** (§8): create a `pyodide venv`, `pip install` the
   wheel into it, run the author+serialize snippet.
10. Upload the wheel as a workflow artifact.

**Job `publish` (needs `build`, only on release / dispatch=pypi):**
- `pypa/gh-action-pypi-publish` with **Trusted Publishing (OIDC)**; target
  TestPyPI or PyPI per input. `id-token: write` permission; environment-gated.

**Considerations:**
- Keep the browser (pyrepl-web) demo test **out** of required CI (needs `bun` +
  a Chrome/headless harness); the Node + `pyodide venv` tests are the automated
  gates. Optionally add a manual/nightly browser job later.
- Pin Emscripten/xbuildenv (`314.0.2`) exactly; a drift changes the ABI tag.
- The `jinja2` configure warning remains harmless (schemas are pre-generated).

---

## 8. Testing strategy

1. **Node harness (`test_usd_import.mjs`)** — reused from PR-B; the primary
   automated gate. Import `Usd/UsdGeom/Sdf/Gf`, author, serialize, round-trip.
2. **`pyodide venv` pip-install test** — new. PEP 783 lets `pip` install a
   `pyemscripten` wheel into a `pyodide venv`. This validates the *published
   metadata + install path* natively in CI (no browser), catching issues the
   Node micropip path might mask:
   ```bash
   pyodide venv .venv-pyodide
   .venv-pyodide/bin/pip install dist/pyodide/grill_usd_core-*.whl
   .venv-pyodide/bin/python -c "from pxr import Usd, UsdGeom; \
       s=Usd.Stage.CreateInMemory(); UsdGeom.Cube.Define(s,'/C'); \
       print(s.GetRootLayer().ExportToString())"
   ```
3. **`twine check`** — metadata/README render validation before upload.
4. **TestPyPI end-to-end** — after upload, `micropip.install('grill-usd-core',
   index_urls=['https://test.pypi.org/simple'])` in the Node harness to prove
   real index resolution.
5. **Browser demo** — manual, against the published `packages="grill-usd-core"`
   (and the local-wheel path), as in PR-B.
6. **Size regression check** — record wheel + `libusd_ms.so` sizes each build;
   a size pass must not break tests 1–2.

---

## 9. Demo & docs updates

- `extras/pyodide/demo/index.html`: switch the canonical example to
  `packages="grill-usd-core"` (network install from PyPI) once published; keep a
  commented local-wheel line (`packages="./grill_usd_core-*.whl"`) for offline
  dev.
- `extras/pyodide/demo/bootstrap.py`: glob `grill_usd_core-*.whl` (local path).
- `extras/pyodide/demo/README.md`: document both install paths and the
  `--dist-name` packaging arg.
- A dedicated **PyPI README** (`build_scripts/pyodide/pypi_readme.md` or similar)
  used as `long_description`, clearly stating: unofficial/experimental,
  WebAssembly-only, not Pixar's `usd-core`, import as `pxr`, cannot coexist with
  `usd-core`.
- `docs/pyodide/PLAN.md`: check off PR-C items; add a short "Distribution"
  section documenting the `grill-usd-core` PyPI channel and the
  `micropip.install`/`packages=` usage.

---

## 10. Risks & mitigations

| # | Risk | Likelihood | Mitigation |
|---|------|-----------|------------|
| R1 | Renamed `*.libs` (`grill_usd_core.libs`) breaks dynamic-lib discovery | Low–Med | Pyodide discovers vendored libs generically; **re-run the full Node + `pyodide venv` gate** immediately after the rename before anything else |
| R2 | PyPI name `grill-usd-core` unavailable / policy issue | Low | Claim it early on PyPI + TestPyPI; if taken, pick an adjacent name and update `--dist-name` |
| R3 | Trusted Publishing / OIDC misconfig | Med | Validate on TestPyPI first; environment-gated `publish` job; fall back to a scoped API token if OIDC blocked |
| R4 | Immutable PyPI versions force churn during iteration | Med | Iterate on TestPyPI with `.devN`; use `.postN` for PyPI re-publishes |
| R5 | Size pass (`-Oz`/`wasm-opt`) changes behavior or load | Med | Gate every size change behind the smoke tests; land size work in a separate commit from the publish plumbing |
| R6 | ABI/toolchain drift (Emscripten/xbuildenv) changes the tag | Low | Pin `314.0.2`; the tag is validated by `twine check` + the `pyodide venv` install |
| R7 | CI build time / flakiness (long monolith compile, oneTBB download) | Med | Cache xbuildenv + oneTBB; `--skip-onetbb`; retry network steps |
| R8 | Users confuse `grill-usd-core` with official `usd-core` | Low | Explicit README disclaimer + `Development Status :: 3 - Alpha`; distinct name |
| R9 | `pxr` import-name collision with `usd-core` | Low | Documented; not installable together, and `usd-core` has no wasm wheel anyway |

---

## 11. Implementation task breakdown (ordered)

Each task is its own commit; validate the risky ones (T1, T4) with an actual
wasm build + Node harness run, not by inspection.

1. **Rename to `grill-usd-core`.** Add `--dist-name` to `package_wheel.py`
   (default `grill-usd-core`). Rebuild + repackage; **re-run the Node harness and
   confirm the `grill_usd_core.libs/libusd_ms.so` still loads and round-trips**
   (R1 gate). Update the demo glob + `packages=`.
2. **Enrich wheel metadata.** long_description (PyPI README), license +
   `LICENSE.txt`, classifiers (incl. `Environment :: WebAssembly :: Emscripten`),
   project URLs, author. Make `twine check` pass.
3. **`pyodide venv` smoke test.** Script + docs; verify pip-install + author/
   serialize locally.
4. **Size hardening.** `-Oz`/`MinSizeRel` build + optional `wasm-opt -Oz`/strip;
   measure and record before/after sizes; keep smoke tests green.
5. **CI workflow.** `.github/workflows/pyodide-wheel.yml`: build + cache +
   package + `twine check` + Node + `pyodide venv` tests; wheel as artifact.
6. **TestPyPI publish.** Trusted Publishing to TestPyPI with a `.devN` version;
   validate via `micropip.install(..., index_urls=[testpypi])` in the harness.
7. **PyPI publish.** Claim `grill-usd-core`; publish the release version via
   Trusted Publishing; validate `micropip.install("grill-usd-core")` and
   `<py-repl packages="grill-usd-core">`.
8. **Demo + docs.** Repoint demo to `packages="grill-usd-core"`; update
   `README.md` and `PLAN.md` (check off PR-C; add Distribution section).

---

## 12. Definition of done for PR-C

- `grill-usd-core` is published on PyPI as a
  `grill_usd_core-<ver>-cp314-cp314-pyemscripten_2026_0_wasm32.whl` and
  `micropip.install("grill-usd-core")` succeeds in the Node harness and the
  browser demo, with the author + serialize round-trip passing.
- A GitHub Actions workflow reproducibly builds, smoke-tests (Node + `pyodide
  venv`), `twine check`s, and publishes the wheel (TestPyPI + PyPI via Trusted
  Publishing).
- Wheel metadata is complete and passes `twine check`, clearly marking the
  package as an unofficial experimental WebAssembly build (not Pixar's
  `usd-core`).
- The wheel is measurably smaller than PR-B's `-O3` build after the size pass,
  with no smoke-test regressions.
- `extras/pyodide/demo/` and `docs/pyodide/PLAN.md` document the
  `grill-usd-core` PyPI channel as the canonical install path.

---

## 13. Open questions / future (PR-D+)

- **Multi-ABI matrix.** When Python 3.15 / `pyemscripten_2027_0` lands, build and
  publish additional wheels under the same version.
- **jsDelivr / CDN mirror.** Optionally mirror the wheel for lower-latency demo
  loads (`micropip` supports the jsDelivr CDN + custom URLs).
- **`cibuildwheel` alternative.** cibuildwheel v4.x can build `pyemscripten`
  wheels, but USD's CMake + oneTBB + monolith flow is better served by the custom
  `build_spike.py`/`package_wheel.py` driver; revisit only if upstreaming.
- **Runtime resolvers / imaging.** Still out of scope (see `PLAN.md`).
