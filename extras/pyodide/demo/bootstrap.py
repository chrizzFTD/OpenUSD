"""Silent startup script for the OpenUSD Pyodide demo.

The usd-core wheel is installed via the ``packages`` attribute on the
``<py-repl>`` element, which micropip-installs it and is awaited *before* this
startup script and the replay run. (A ``src`` startup script cannot install the
wheel itself because pyrepl exec's it synchronously and it cannot await
``micropip.install``.)

Importing ``pxr`` here runs the wheel's bundled plugin-path bootstrap, which
registers the vendored ``pxr/pluginfo/`` with the live Plug registry before the
demo replay uses ``Sdf``/``Usd``.
"""
import pxr  # noqa: F401
