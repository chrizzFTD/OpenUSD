#!/usr/bin/env python3
"""Package a minimal Pyodide wheel containing only pxr.Tf (PR-A browser test).

Expects a completed Pyodide spike build tree (see build_spike.py) with:
  - pxr/base/tf/_tf.so (static monolith linked in via WHOLE_ARCHIVE)

Usage:
  python build_scripts/pyodide/package_tf_spike_wheel.py \\
      --build-root /tmp/usd-pyodide-spike \\
      --output-dir dist/pyodide
"""
from __future__ import annotations

import argparse
import pathlib
import shutil
import subprocess
import sys


SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent
DEFAULT_SETUP = SCRIPT_DIR / "wheel_staging" / "setup.py"


def run(cmd: list[str], *, cwd: pathlib.Path | None = None) -> None:
    print("+", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run(cmd, cwd=cwd, check=True)


def ensure_wheel_cli() -> None:
    """auditwheel-emscripten invokes the ``wheel`` CLI."""
    wheel_shim = pathlib.Path.home() / ".local" / "bin" / "wheel"
    if not wheel_shim.is_file():
        wheel_shim.parent.mkdir(parents=True, exist_ok=True)
        wheel_shim.write_text("#!/bin/sh\nexec python3 -m wheel \"$@\"\n")
        wheel_shim.chmod(0o755)


def stage_wheel(
    *,
    build_root: pathlib.Path,
    stage_dir: pathlib.Path,
    version: str,
) -> tuple[pathlib.Path, pathlib.Path]:
    usd_build = build_root / "usd-build"
    tf_so = usd_build / "pxr" / "base" / "tf" / "_tf.so"
    if not tf_so.is_file():
        raise FileNotFoundError(
            f"Missing {tf_so}. Run build_spike.py --build-target _tf first."
        )

    if stage_dir.exists():
        shutil.rmtree(stage_dir)
    libdir = stage_dir / "lib"
    pxr_dir = stage_dir / "lib" / "python" / "pxr"
    tf_dir = pxr_dir / "Tf"
    tf_dir.mkdir(parents=True)
    (pxr_dir / "__init__.py").write_text("__all__ = ['Tf']\n")
    shutil.copy2(REPO_ROOT / "pxr" / "base" / "tf" / "__init__.py", tf_dir / "__init__.py")
    shutil.copy2(tf_so, tf_dir / "_tf.so")

    setup_py = stage_dir / "setup.py"
    setup_template = DEFAULT_SETUP.read_text()
    setup_py.write_text(setup_template.replace("@VERSION@", version))
    return libdir, stage_dir


def build_and_repair(
    stage_dir: pathlib.Path,
    libdir: pathlib.Path,
    output_dir: pathlib.Path,
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

    # auditwheel repair may assert on post-repair introspection but still writes
    # the wheel; tolerate non-zero exit if the artifact exists.
    proc = subprocess.run(
        [
            "pyodide",
            "auditwheel",
            "repair",
            "--libdir",
            str(libdir),
            str(unrepaired),
            "--output-dir",
            str(output_dir),
        ],
        check=False,
    )
    if not repaired.is_file():
        raise RuntimeError(
            f"pyodide auditwheel repair failed (exit {proc.returncode})"
        )
    if proc.returncode != 0:
        print(
            f"WARNING: auditwheel repair exited {proc.returncode} "
            f"but wheel was written: {repaired}",
            file=sys.stderr,
        )
    return repaired


def main() -> None:
    parser = argparse.ArgumentParser(description="Package pxr.Tf Pyodide spike wheel")
    parser.add_argument(
        "--build-root",
        type=pathlib.Path,
        default=REPO_ROOT / "build" / "pyodide-spike",
        help="build_spike.py working directory",
    )
    parser.add_argument(
        "--output-dir",
        type=pathlib.Path,
        default=REPO_ROOT / "dist" / "pyodide",
        help="directory for repaired wheel output",
    )
    parser.add_argument("--version", default="0.0.1", help="wheel version")
    parser.add_argument(
        "--stage-dir",
        type=pathlib.Path,
        default=None,
        help="keep intermediate staging tree (default: temp under build-root)",
    )
    args = parser.parse_args()

    if shutil.which("pyodide") is None:
        print("ERROR: pyodide CLI not found (pip install pyodide-build)", file=sys.stderr)
        sys.exit(1)

    stage_dir = args.stage_dir or (args.build_root / "wheel-stage")
    libdir, stage_dir = stage_wheel(
        build_root=args.build_root,
        stage_dir=stage_dir,
        version=args.version,
    )
    wheel = build_and_repair(stage_dir, libdir, args.output_dir)
    print(f"\nRepaired wheel: {wheel}")


if __name__ == "__main__":
    main()
