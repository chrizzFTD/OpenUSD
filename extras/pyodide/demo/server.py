#!/usr/bin/env python3
"""Single-origin static server for the OpenUSD Pyodide demo.

Serves the demo directory at ``/`` and the pyrepl-web ``grill`` build under
``/pyrepl/`` from one origin, so the browser's cross-origin dynamic ES-module
import of ``pyrepl.esm.js`` does not require CORS headers (which plain
``python -m http.server`` does not send). CORS headers are also added as a
belt-and-braces measure.

Usage:
  python server.py [--port 8765] [--pyrepl-dist ../../../../pyrepl-web/dist]

Then open http://localhost:8765/index.html
"""
from __future__ import annotations

import argparse
import http.server
import pathlib


DEMO_DIR = pathlib.Path(__file__).resolve().parent


def make_handler(pyrepl_dist: pathlib.Path):
    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(DEMO_DIR), **kwargs)

        def translate_path(self, path):
            # Route /pyrepl/* to the pyrepl-web dist directory.
            clean = path.split("?", 1)[0].split("#", 1)[0]
            if clean.startswith("/pyrepl/"):
                rel = clean[len("/pyrepl/"):].lstrip("/")
                return str(pyrepl_dist / rel)
            return super().translate_path(path)

        def end_headers(self):
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cross-Origin-Opener-Policy", "same-origin")
            self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
            super().end_headers()

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--pyrepl-dist",
        type=pathlib.Path,
        default=DEMO_DIR / ".." / ".." / ".." / ".." / "pyrepl-web" / "dist",
        help="path to the built pyrepl-web dist directory (grill branch)",
    )
    args = parser.parse_args()
    pyrepl_dist = args.pyrepl_dist.resolve()
    if not (pyrepl_dist / "pyrepl.js").is_file():
        print(f"WARNING: {pyrepl_dist}/pyrepl.js not found; build pyrepl-web first.")

    handler = make_handler(pyrepl_dist)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    print(f"Serving demo at http://localhost:{args.port}/index.html")
    print(f"  pyrepl dist: {pyrepl_dist}  ->  /pyrepl/")
    server.serve_forever()


if __name__ == "__main__":
    main()
