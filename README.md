# c2pip

`c2pip` is **Buildozer for C -> pip**. It takes any C header or source file, automatically generates the CPython wrapper boilerplate (`PyArg_ParseTuple`, `PyMethodDef`), sets up a robust `pyproject.toml` with zero PyPI validation headaches, compiles native wheels, and uploads them straight to PyPI.

---

## The 3-Step Flow

```bash
c2pip init _math.h --name dan-pyda --author "Sampath"
c2pip build
c2pip publish
```
# Features
Automated C Parsing & Wrapper Generation: Scans C headers/functions and constructs _wrapper.c natively.
PyPI Proofing: Enforces strict metadata formatting (license = {text="MIT"}, proper classifiers, URLs, and a mandatory README.md) so you never fight a PyPI validation error again.
Buildozer Simplicity: One tool to initialize, compile binary wheels, and publish.
