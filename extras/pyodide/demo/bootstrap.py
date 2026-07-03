"""Install the co-hosted usd-tf-pyodide-spike wheel before the REPL starts."""
import asyncio
import glob
import micropip


def _wheel_url() -> str:
    wheels = sorted(glob.glob("./usd_tf_pyodide_spike-*.whl"))
    if not wheels:
        raise RuntimeError(
            "No usd_tf_pyodide_spike-*.whl in demo directory. "
            "Run package_tf_spike_wheel.py and copy the wheel here."
        )
    # Relative URL — same origin as this page.
    return f"./{wheels[-1].split('/')[-1]}"


async def _install() -> None:
    url = _wheel_url()
    print(f"Installing {url} …")
    await micropip.install(url)
    print("usd-tf-pyodide-spike installed.")


asyncio.ensure_future(_install())
