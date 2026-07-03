"""Replay script: verify pxr.Tf imports in the browser REPL."""
from pxr import Tf

parts = Tf.StringSplit("hello from Pyodide 314", " ")
print("from pxr import Tf -> OK")
print("Tf.StringSplit(...) =", parts)
