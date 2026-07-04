"""Guided USD scripting demo (Pyodide 314, full usd-core wheel).

Authors a small stage, exercises a few schemas, and serializes to .usda to
prove the shared libusd_ms.so side module + plugin registry work in-browser.
"""
from pxr import Usd, UsdGeom, Sdf, Gf

# Anonymous layer creation exercises the Sdf usda file format plugin (and the
# Ar default resolver) — i.e. the runtime plugin registry.
stage = Usd.Stage.CreateInMemory()

world = UsdGeom.Xform.Define(stage, "/World")
cube = UsdGeom.Cube.Define(stage, "/World/Cube")
cube.GetSizeAttr().Set(2.0)

# Cross-module Boost.Python type flow: Gf.Vec3d -> UsdGeom -> Sdf value.
UsdGeom.XformCommonAPI(world).SetTranslate(Gf.Vec3d(1.0, 2.0, 3.0))
stage.SetDefaultPrim(world.GetPrim())

print("Default prim:", stage.GetDefaultPrim().GetName())
print("Cube size:", cube.GetSizeAttr().Get())
print("Prims:", [p.GetPath().pathString for p in stage.Traverse()])

usda = stage.GetRootLayer().ExportToString()
print("\n--- serialized .usda ---")
print(usda)

# Round-trip: reimport the serialized text.
layer = Sdf.Layer.CreateAnonymous(".usda")
assert layer.ImportFromString(usda)
reloaded = Usd.Stage.Open(layer)
assert reloaded.GetPrimAtPath("/World/Cube")
print("Round-trip OK ->", reloaded.GetPrimAtPath("/World/Cube").GetPath())
