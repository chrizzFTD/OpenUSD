import setuptools
from wheel.bdist_wheel import bdist_wheel


class EmscriptenBdistWheel(bdist_wheel):
    def get_tag(self):
        return ("cp314", "cp314", "pyemscripten_2026_0_wasm32")


setuptools.setup(
    name="usd-tf-pyodide-spike",
    version="@VERSION@",
    packages=setuptools.find_packages("lib/python"),
    package_dir={"": "lib/python"},
    package_data={"": ["*.so"], "pxr.Tf": ["*.so"]},
    cmdclass={"bdist_wheel": EmscriptenBdistWheel},
    zip_safe=False,
)
