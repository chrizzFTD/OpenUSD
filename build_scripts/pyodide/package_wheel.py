#!/usr/bin/env python3
"""Package the full usd-core Pyodide 314 wheel (PR-B).

Consumes a USD install tree produced by ``build_spike.py --build-target install``
(cross-built for Emscripten / Pyodide 314) and produces a
``usd_core-<ver>-cp314-cp314-pyemscripten_2026_0_wasm32.whl`` that ships the C++
core once as a vendored ``.libs/libusd_ms.so`` shared side module, with thin
``_*.so`` extension modules dynamically linking against it, plus the runtime
plugin registry under ``pxr/pluginfo/``.

Layout mirrors the native PyPI relocation (build_scripts/pypi/package_files/
setup.py) adapted for a single monolithic Emscripten side module.

Usage:
  # Build + install first (or pass --skip-build if inst/ already exists):
  python build_scripts/pyodide/build_spike.py --skip-onetbb --build-target install
  python build_scripts/pyodide/package_wheel.py \
      --build-root build/pyodide-spike \
      --output-dir dist/pyodide
"""
from __future__ import annotations

import argparse
import pathlib
import re
import shutil
import subprocess
import sys


SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent

# Bootstrap appended to the installed top-level pxr/__init__.py so Plug finds the
# vendored plugin registry.
#
# Unlike a native install, Pyodide eagerly loads every extension .so (and thus
# libusd_ms.so) at *wheel-install* time, before `import pxr` ever runs. Plug's
# ARCH_CONSTRUCTOR (Plug_InitConfig) therefore builds its search path from
# PXR_PLUGINPATH_NAME during install, when this module has not executed yet, so
# merely setting the env var here is too late. Instead we actively register the
# vendored pluginfo directory at import time via Plug.Registry().RegisterPlugins,
# which augments the already-initialized registry. We still set the env var as a
# belt-and-braces fallback for any later re-read.
PLUGIN_PATH_BOOTSTRAP = '''

# --- Pyodide: register the vendored plugin registry ------------------------
import os as _os
_pluginfo = _os.path.join(_os.path.dirname(_os.path.realpath(__file__)), "pluginfo")
if _os.path.isdir(_pluginfo):
    _existing = _os.environ.get("PXR_PLUGINPATH_NAME", "")
    _os.environ["PXR_PLUGINPATH_NAME"] = (
        _pluginfo + (_os.pathsep + _existing if _existing else "")
    )
    # Extension .so are eagerly loaded at wheel-install time, so Plug's
    # search path was already built without the env var above; actively
    # register the vendored pluginfo with the live registry.
    from pxr import Plug as _Plug
    _Plug.Registry().RegisterPlugins(_pluginfo)
    del _Plug, _existing
del _os, _pluginfo
# --------------------------------------------------------------------------
'''


SETUP_PY_TEMPLATE = '''\
import glob
import os

import setuptools
from wheel.bdist_wheel import bdist_wheel


class EmscriptenBdistWheel(bdist_wheel):
    def get_tag(self):
        return ("cp314", "cp314", "pyemscripten_2026_0_wasm32")


PYTHON_LIB_DIR = "lib/python"
PXR_DIR = os.path.join(PYTHON_LIB_DIR, "pxr")
PLUGINFO_DIR = os.path.join(PXR_DIR, "pluginfo")

# Ship every file under pxr/pluginfo/ (plugInfo.json, generatedSchema.usda,
# schema.usda, shaders/*, ...) as package data, referenced relative to pxr/.
pluginfo_files = [
    os.path.relpath(f, PXR_DIR)
    for f in glob.glob(os.path.join(PLUGINFO_DIR, "**", "*"), recursive=True)
    if os.path.isfile(f)
]

setuptools.setup(
    name="usd-core",
    version="@VERSION@",
    description="Pixar's Universal Scene Description (Pyodide 314 / wasm32)",
    packages=setuptools.find_packages(PYTHON_LIB_DIR),
    package_dir={"": PYTHON_LIB_DIR},
    package_data={
        # Extension modules and every pure-Python companion shipped alongside
        # the generated bindings (usdGenSchema.py, codegenTemplates/**, etc.).
        "": ["*.so"],
        "pxr": pluginfo_files,
    },
    include_package_data=True,
    cmdclass={"bdist_wheel": EmscriptenBdistWheel},
    zip_safe=False,
    python_requires=">=3.14, <3.15",
)
'''


def run(cmd: list[str], *, cwd: pathlib.Path | None = None) -> None:
    print("+", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run([str(c) for c in cmd], cwd=cwd, check=True)


def ensure_wheel_cli() -> None:
    """auditwheel-emscripten invokes the ``wheel`` CLI."""
    wheel_shim = pathlib.Path.home() / ".local" / "bin" / "wheel"
    if not wheel_shim.is_file():
        wheel_shim.parent.mkdir(parents=True, exist_ok=True)
        wheel_shim.write_text('#!/bin/sh\nexec python3 -m wheel "$@"\n')
        wheel_shim.chmod(0o755)


def detect_version(inst: pathlib.Path, override: str | None) -> str:
    if override:
        return override
    header = inst / "include" / "pxr" / "pxr.h"
    minor = patch = None
    if header.is_file():
        for line in header.read_text().splitlines():
            m = re.match(r"#define PXR_MINOR_VERSION (\d+)", line)
            if m:
                minor = m.group(1)
            m = re.match(r"#define PXR_PATCH_VERSION (\d+)", line)
            if m:
                patch = m.group(1)
    if minor is not None and patch is not None:
        return f"{minor}.{patch}"
    return "0.0.0"


def stage_wheel(
    *, inst: pathlib.Path, stage_dir: pathlib.Path, version: str
) -> tuple[pathlib.Path, pathlib.Path]:
    """Assemble the wheel staging tree from the USD install directory."""
    pxr_src = inst / "lib" / "python" / "pxr"
    if not (pxr_src / "__init__.py").is_file():
        raise FileNotFoundError(
            f"Missing {pxr_src}/__init__.py. Run build_spike.py "
            "--build-target install first."
        )
    monolith = inst / "lib" / "libusd_ms.so"
    if not monolith.is_file():
        raise FileNotFoundError(
            f"Missing shared monolith {monolith}. The Pyodide build must "
            "produce libusd_ms.so (-sSIDE_MODULE=1)."
        )

    if stage_dir.exists():
        shutil.rmtree(stage_dir)
    lib_python = stage_dir / "lib" / "python"
    lib_python.mkdir(parents=True)
    pxr_dst = lib_python / "pxr"

    # 1. Copy the whole pxr Python package (extensions + pure-Python companions).
    shutil.copytree(pxr_src, pxr_dst)

    # 2. Relocate the plugin registry into pxr/pluginfo/. inst/lib/usd holds the
    #    aggregator + per-library resources; inst/plugin/usd/* holds C++ plugin
    #    resources (e.g. usdShaders). This breaks the native relative paths, but
    #    LibraryPath is empty for the monolithic core so there is no dlopen and
    #    the runtime plugin path (pxr/__init__.py bootstrap) fixes discovery.
    pluginfo_dst = pxr_dst / "pluginfo"
    lib_usd = inst / "lib" / "usd"
    if lib_usd.is_dir():
        shutil.copytree(lib_usd, pluginfo_dst)
    else:
        pluginfo_dst.mkdir(parents=True)
    plugin_usd = inst / "plugin" / "usd"
    if plugin_usd.is_dir():
        for child in plugin_usd.iterdir():
            dest = pluginfo_dst / child.name
            if child.is_dir():
                shutil.copytree(child, dest, dirs_exist_ok=True)
            else:
                shutil.copy2(child, dest)

    # 3. Append the runtime plugin-path bootstrap to the top-level __init__.py.
    init_py = pxr_dst / "__init__.py"
    init_py.write_text(init_py.read_text() + PLUGIN_PATH_BOOTSTRAP)

    # 4. Emit setup.py.
    (stage_dir / "setup.py").write_text(
        SETUP_PY_TEMPLATE.replace("@VERSION@", version)
    )

    return inst / "lib", stage_dir


def build_and_repair(
    *, stage_dir: pathlib.Path, libdir: pathlib.Path, output_dir: pathlib.Path
) -> pathlib.Path:
    ensure_wheel_cli()
    run([sys.executable, "setup.py", "bdist_wheel"], cwd=stage_dir)
    wheels = list((stage_dir / "dist").glob("*.whl"))
    if not wheels:
        raise RuntimeError("bdist_wheel produced no output")
    unrepaired = wheels[0]

    output_dir.mkdir(parents=True, exist_ok=True)
    repaired = output_dir / unrepaired.name
    if repaired.exists():
        repaired.unlink()

    # auditwheel repair vendors libusd_ms.so into .libs/ and writes the
    # $ORIGIN-relative RUNTIME_PATH into every _*.so dylink.0 section. It may
    # exit non-zero on post-repair introspection but still write the wheel.
    proc = subprocess.run(
        [
            "pyodide", "auditwheel", "repair",
            "--libdir", str(libdir),
            str(unrepaired),
            "--output-dir", str(output_dir),
        ],
        check=False,
    )
    if not repaired.is_file():
        raise RuntimeError(
            f"pyodide auditwheel repair failed (exit {proc.returncode})"
        )
    if proc.returncode != 0:
        print(
            f"WARNING: auditwheel repair exited {proc.returncode} but wheel "
            f"was written: {repaired}",
            file=sys.stderr,
        )
    return repaired


def main() -> None:
    parser = argparse.ArgumentParser(description="Package the usd-core Pyodide wheel")
    parser.add_argument(
        "--build-root",
        type=pathlib.Path,
        default=REPO_ROOT / "build" / "pyodide-spike",
        help="build_spike.py working directory (contains inst/)",
    )
    parser.add_argument(
        "--inst",
        type=pathlib.Path,
        default=None,
        help="USD install prefix (default: <build-root>/inst)",
    )
    parser.add_argument(
        "--output-dir",
        type=pathlib.Path,
        default=REPO_ROOT / "dist" / "pyodide",
        help="directory for repaired wheel output",
    )
    parser.add_argument("--version", default=None, help="wheel version override")
    parser.add_argument(
        "--stage-dir",
        type=pathlib.Path,
        default=None,
        help="staging tree (default: <build-root>/wheel-stage)",
    )
    args = parser.parse_args()

    if shutil.which("pyodide") is None:
        print("ERROR: pyodide CLI not found (pip install pyodide-build)", file=sys.stderr)
        sys.exit(1)

    inst = args.inst or (args.build_root / "inst")
    version = detect_version(inst, args.version)
    stage_dir = args.stage_dir or (args.build_root / "wheel-stage")

    libdir, stage_dir = stage_wheel(inst=inst, stage_dir=stage_dir, version=version)
    wheel = build_and_repair(
        stage_dir=stage_dir, libdir=libdir, output_dir=args.output_dir
    )
    print(f"\nRepaired usd-core wheel: {wheel}")


if __name__ == "__main__":
    main()
