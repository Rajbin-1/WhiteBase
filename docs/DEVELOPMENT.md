# Development Guide

## Environment

Use Python 3.10 or newer. The White Base core has no third-party runtime
dependencies. No model weights or ML frameworks are needed for core tests.

## Run focused tests

```powershell
python -m unittest discover -s tests -p test_whitebase.py -v
python -m unittest discover -s tests -p test_architecture_contracts.py -v
python -m unittest discover -s tests/stress -p test_whitebase_stress.py -v
python -m unittest discover -s tests/performance -p test_whitebase_performance.py -v
```

## Build and install

Build a wheel without installing optional dependencies:

```powershell
python -m pip wheel --no-deps . --wheel-dir dist
```

Install the core package with `python -m pip install .`.

## Build a Brick

1. Define a `manifest.json` following the [Brick specification](BRICK_SPEC.md).
2. Package the manifest, connector, and required resources into a `.wb` ZIP.
3. Validate and install it with the White Base CLI or Python runtime.
4. Add focused tests for manifest validation, routing, and connector lifecycle.

Connectors run as trusted in-process Python. Do not install packages from
untrusted sources.
