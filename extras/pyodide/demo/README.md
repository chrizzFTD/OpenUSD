# USD Pyodide Tf spike — browser demo (PR-A)

Interactive browser test for the minimal `usd-tf-pyodide-spike` wheel using
**[pyrepl-web `grill`](https://github.com/chrizzFTD/pyrepl-web/tree/grill)** as the
REPL runtime. No changes to pyrepl-web — only consume its built `pyrepl.js`.

## Prerequisites

1. **Pyodide spike build** (`_tf.so` with static monolith linked in):

   ```bash
   pip install 'pyodide-build>=0.36' jinja2 wheel
   pyodide xbuildenv install 314.0.2 --force && pyodide xbuildenv use 314.0.2
   pyodide xbuildenv install-emscripten
   python build_scripts/pyodide/build_spike.py --build-target _tf \
       --build-root /tmp/usd-pyodide-spike
   ```

2. **Package the wheel**:

   ```bash
   python build_scripts/pyodide/package_tf_spike_wheel.py \
       --build-root /tmp/usd-pyodide-spike \
       --output-dir dist/pyodide
   cp dist/pyodide/usd_tf_pyodide_spike-*.whl extras/pyodide/demo/
   ```

3. **pyrepl-web `grill`** (sibling clone, build once):

   ```bash
   git clone -b grill https://github.com/chrizzFTD/pyrepl-web.git ../pyrepl-web
   cd ../pyrepl-web && bun install && bun run build
   ```

## Serve the demo

From the **repo root**, serve demo assets and pyrepl `dist/` (example using Python):

```bash
# Terminal 1 — demo + wheel
python3 -m http.server 8765 --directory extras/pyodide/demo

# Terminal 2 — pyrepl.js (adjust path to your pyrepl-web clone)
python3 -m http.server 8766 --directory ../pyrepl-web/dist
```

Open `http://localhost:8765/index.html` and edit `index.html` if your pyrepl
port/path differs.

## Automated smoke test (Node, no browser)

```bash
cd build_scripts/pyodide && npm install
node test_tf_import.mjs ../../dist/pyodide/usd_tf_pyodide_spike-*.whl
```

Expected output: `from pxr import Tf -> OK`

## What success looks like

- **Node harness**: `from pxr import Tf` imports without error
- **Browser**: pyrepl REPL runs `test_tf.py` replay; prints `Tf.StringSplit(...)`
