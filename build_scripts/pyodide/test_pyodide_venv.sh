#!/usr/bin/env bash
# PR-C smoke test: pip-install the grill-usd-core wheel into a `pyodide venv`
# and author + serialize a stage (PEP 783 native install path, no browser).
#
# This validates the published metadata + install path natively (pip resolves
# the pyemscripten_2026_0_wasm32 tag inside the venv), catching issues the Node
# micropip harness might mask.
#
# Requirements: a *host* CPython matching the xbuildenv (3.14 for Pyodide 314)
# with pyodide-build installed — `pyodide venv` refuses a mismatched host.
# Set PYODIDE_CLI to that interpreter's pyodide entry point if it is not the
# first `pyodide` on PATH (e.g. PYODIDE_CLI=/tmp/host314/bin/pyodide).
#
# Usage (from repo root, after package_wheel.py):
#   build_scripts/pyodide/test_pyodide_venv.sh dist/pyodide/grill_usd_core-*.whl
set -euo pipefail

WHEEL=${1:?usage: test_pyodide_venv.sh <path-to-wheel> [venv-dir]}
VENV=${2:-$(mktemp -d)/venv-pyodide}
PYODIDE_CLI=${PYODIDE_CLI:-pyodide}

echo "Creating pyodide venv at ${VENV}"
"${PYODIDE_CLI}" venv "${VENV}"

echo "Installing ${WHEEL}"
"${VENV}/bin/pip" install "${WHEEL}"

echo "Running author + serialize round-trip"
"${VENV}/bin/python" - <<'EOF'
from pxr import Usd, UsdGeom, Sdf, Gf

stage = Usd.Stage.CreateInMemory()
world = UsdGeom.Xform.Define(stage, "/World")
cube = UsdGeom.Cube.Define(stage, "/World/Cube")
cube.GetSizeAttr().Set(2.0)
UsdGeom.XformCommonAPI(world).SetTranslate(Gf.Vec3d(1.0, 2.0, 3.0))
stage.SetDefaultPrim(world.GetPrim())

usda = stage.GetRootLayer().ExportToString()
assert 'def Xform "World"' in usda, usda
assert 'def Cube "Cube"' in usda, usda
assert "double size = 2" in usda, usda

layer = Sdf.Layer.CreateAnonymous(".usda")
assert layer.ImportFromString(usda), "ImportFromString failed"
reloaded = Usd.Stage.Open(layer)
assert reloaded.GetPrimAtPath("/World/Cube"), "round-trip prim missing"

print("pyodide venv: from pxr import Usd, UsdGeom, Sdf, Gf -> OK")
print("pyodide venv: authored + serialized stage round-trip -> OK")
EOF
