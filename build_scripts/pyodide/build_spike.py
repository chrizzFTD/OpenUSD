#!/usr/bin/env python3
#
# Phase 0 spike: build OpenUSD Tf Python bindings for Pyodide 314.
#
# Uses the pyodide-build cross environment (Python 3.14.2 / Emscripten 5.0.3)
# rather than the OpenUSD wasm CI toolchain (Emscripten 5.0.7, no Python).
#
# Prerequisites:
#   pip install 'pyodide-build>=0.36'
#   pyodide xbuildenv install 314.0.2 --force
#   pyodide xbuildenv use 314.0.2
#
# Usage:
#   python build_scripts/pyodide/build_spike.py --inst /tmp/usd-pyodide-spike
#   python build_scripts/pyodide/build_spike.py --inst /tmp/usd-pyodide-spike --build-target _tf
#
from __future__ import annotations

import argparse
import os
import pathlib
import shutil
import subprocess
import sys
import zipfile
from urllib.request import urlretrieve

ONETBB_URL = (
    "https://github.com/oneapi-src/oneTBB/archive/refs/tags/v2021.12.0.zip"
)
ONETBB_VERSION_DIR = "oneTBB-2021.12.0"

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent
DEFAULT_BUILD_ROOT = REPO_ROOT / "build" / "pyodide-spike"


def run(cmd: list[str | pathlib.Path], *, cwd: pathlib.Path | None = None, env: dict | None = None) -> None:
    str_cmd = [str(c) for c in cmd]
    print("+", " ".join(str_cmd), flush=True)
    subprocess.run(str_cmd, cwd=cwd, env=env, check=True)


def pyodide_config(key: str) -> str:
    result = subprocess.run(
        ["pyodide", "config", "get", key],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip().strip('"')


def ensure_pyodide_314() -> None:
  """Verify pyodide xbuildenv is Python 3.14 / Emscripten 5.0.3."""
  py_ver = pyodide_config("python_version")
  emsdk_ver = pyodide_config("emscripten_version")
  if not py_ver.startswith("3.14"):
      print(
          f"ERROR: pyodide xbuildenv has Python {py_ver}; need 3.14.x.\n"
          "Run: pyodide xbuildenv install 314.0.2 --force && pyodide xbuildenv use 314.0.2",
          file=sys.stderr,
      )
      sys.exit(1)
  if not emsdk_ver.startswith("5.0.3"):
      print(
          f"WARNING: pyodide xbuildenv has Emscripten {emsdk_ver}; expected 5.0.3",
          file=sys.stderr,
      )


def emsdk_env() -> dict[str, str]:
    env = os.environ.copy()
    emsdk_dir = pyodide_config("emsdk_dir")
    emsdk_env_sh = pathlib.Path(emsdk_dir) / "emsdk_env.sh"
    if not emsdk_env_sh.is_file():
        print("Emscripten SDK not installed; running pyodide xbuildenv install-emscripten …")
        run(["pyodide", "xbuildenv", "install-emscripten"])
    result = subprocess.run(
        f'source "{emsdk_env_sh}" && env -0',
        shell=True,
        executable="/bin/bash",
        capture_output=True,
        check=True,
    )
    for entry in result.stdout.split(b"\0"):
        if b"=" in entry:
            key, _, value = entry.partition(b"=")
            env[key.decode()] = value.decode()
    return env


def download_onetbb(dest: pathlib.Path) -> pathlib.Path:
    dest.mkdir(parents=True, exist_ok=True)
    zip_path = dest / "onetbb.zip"
    src_dir = dest / ONETBB_VERSION_DIR
    if not src_dir.exists():
        print(f"Downloading oneTBB from {ONETBB_URL}")
        urlretrieve(ONETBB_URL, zip_path)
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(dest)
    return src_dir


def build_onetbb(onetbb_src: pathlib.Path, install_dir: pathlib.Path, env: dict) -> None:
    build_dir = onetbb_src.parent / "onetbb-build"
    if (install_dir / "lib" / "libtbb.a").exists():
        print(f"oneTBB already built at {install_dir}")
        return

    # Pyodide/pyemscripten ABI forbids -pthread on SIDE_MODULE wheels (see
    # https://pyodide.org/en/stable/development/abi/flags.html). USD wasm CI
    # uses -pthread, but the Pyodide path must not.
    cxx_flags = "-fwasm-exceptions -sSUPPORT_LONGJMP=wasm -sUSE_PTHREADS=0"
    cmake_args = [
        "emcmake", "cmake",
        f"-DCMAKE_INSTALL_PREFIX={install_dir}",
        "-DCMAKE_BUILD_TYPE=Release",
        "-DBUILD_SHARED_LIBS=OFF",
        "-DTBB_TEST=OFF",
        "-DTBB_STRICT=OFF",
        f"-DCMAKE_CXX_FLAGS={cxx_flags}",
        f"-DCMAKE_C_FLAGS={cxx_flags}",
        f"-S{onetbb_src}",
        f"-B{build_dir}",
    ]
    run(cmake_args, env=env)
    run(["cmake", "--build", build_dir, "--target", "install", "-j", str(os.cpu_count() or 4)], env=env)


def touch_dummy_libpython(python_include: str) -> pathlib.Path:
    """Work around FindPython Development requiring a libpython on disk."""
    include_dir = pathlib.Path(python_include)
    # .../include/python3.14 -> .../lib/libpython3.14.so
    version_tag = include_dir.name  # python3.14
    lib_dir = include_dir.parent.parent / "lib"
    dummy_lib = lib_dir / f"lib{version_tag}.so"
    lib_dir.mkdir(parents=True, exist_ok=True)
    if not dummy_lib.exists():
        dummy_lib.touch()
    print(f"Using dummy libpython at {dummy_lib}")
    return dummy_lib


def configure_usd(
    *,
    build_dir: pathlib.Path,
    install_dir: pathlib.Path,
    tbb_dir: pathlib.Path,
    env: dict,
) -> None:
    python_executable = pyodide_config("interpreter")
    python_include = pyodide_config("python_include_dir")
    toolchain = pyodide_config("cmake_toolchain_file")

    dummy_libpython = touch_dummy_libpython(python_include)

    cxx_flags = "-fwasm-exceptions -sSUPPORT_LONGJMP=wasm -sUSE_PTHREADS=0"
    cmake_args = [
        "emcmake", "cmake",
        f"-DCMAKE_TOOLCHAIN_FILE={toolchain}",
        f"-DCMAKE_INSTALL_PREFIX={install_dir}",
        f"-DCMAKE_BUILD_TYPE=Release",
        f"-DCMAKE_FIND_ROOT_PATH={tbb_dir}",
        f"-DPython3_EXECUTABLE={python_executable}",
        f"-DPython3_INCLUDE_DIR={python_include}",
        f"-DPython3_LIBRARY={dummy_libpython}",
        f"-DPython3_FIND_STRATEGY=LOCATION",
        f"-DPython3_FIND_FRAMEWORK=NEVER",
        f"-DPython3_FIND_REGISTRY=NEVER",
        "-DPXR_BUILD_PYODIDE=ON",
        "-DPXR_ENABLE_PYTHON_SUPPORT=ON",
        "-DPXR_PY_UNDEFINED_DYNAMIC_LOOKUP=ON",
        "-DPXR_BUILD_MONOLITHIC=ON",
        "-DBUILD_SHARED_LIBS=ON",
        "-DPXR_BUILD_IMAGING=OFF",
        "-DPXR_BUILD_USD_TOOLS=OFF",
        "-DPXR_BUILD_TESTS=OFF",
        "-DPXR_BUILD_EXAMPLES=OFF",
        "-DPXR_BUILD_TUTORIALS=OFF",
        "-DPXR_BUILD_EXEC=OFF",
        "-DPXR_BUILD_USD_VALIDATION=OFF",
        "-DPXR_BUILD_DOCUMENTATION=OFF",
        "-DPXR_PYTHON_INSTALL_DIR=lib/python",
        f"-DTBB_INCLUDE_DIRS={tbb_dir}/include",
        f"-DTBB_tbb_LIBRARY_RELEASE={tbb_dir}/lib/libtbb.a",
        f"-DTBB_tbb_LIBRARY_DEBUG={tbb_dir}/lib/libtbb.a",
        f"-DCMAKE_CXX_FLAGS={cxx_flags}",
        f"-DCMAKE_C_FLAGS={cxx_flags}",
        f"-DCMAKE_EXE_LINKER_FLAGS=",
        f"-S{REPO_ROOT}",
        f"-B{build_dir}",
    ]
    run(cmake_args, env=env)


def build_usd(build_dir: pathlib.Path, target: str, env: dict) -> None:
    run(
        ["cmake", "--build", build_dir, "--target", target, "-j", str(os.cpu_count() or 4)],
        env=env,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Pyodide 314 Tf binding spike build")
    parser.add_argument(
        "--inst",
        type=pathlib.Path,
        default=DEFAULT_BUILD_ROOT / "inst",
        help="USD install prefix",
    )
    parser.add_argument(
        "--build-root",
        type=pathlib.Path,
        default=DEFAULT_BUILD_ROOT,
        help="Working directory for deps and cmake build",
    )
    parser.add_argument(
        "--build-target",
        default="_tf",
        help="CMake target to build (default: _tf python module)",
    )
    parser.add_argument(
        "--configure-only",
        action="store_true",
        help="Run cmake configure without building",
    )
    parser.add_argument(
        "--skip-onetbb",
        action="store_true",
        help="Skip oneTBB build (use existing install in build-root/tbb)",
    )
    args = parser.parse_args()

    if shutil.which("pyodide") is None:
        print("ERROR: pyodide CLI not found. pip install pyodide-build", file=sys.stderr)
        sys.exit(1)

    ensure_pyodide_314()
    env = emsdk_env()

    tbb_install = args.build_root / "tbb"
    usd_build = args.build_root / "usd-build"

    if not args.skip_onetbb:
        onetbb_src = download_onetbb(args.build_root / "downloads")
        build_onetbb(onetbb_src, tbb_install, env)

    configure_usd(
        build_dir=usd_build,
        install_dir=args.inst,
        tbb_dir=tbb_install,
        env=env,
    )

    if not args.configure_only:
        build_usd(usd_build, args.build_target, env)
        print(f"\nSpike build complete. Install tree: {args.inst}")
        print("Next: package _tf.so into a pyemscripten wheel and test with pyodide venv.")


if __name__ == "__main__":
    main()
