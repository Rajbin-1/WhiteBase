# White Base

White Base (WhiteAS) is a lightweight, local-first runtime for installing,
discovering, routing, and managing independent AI capability packages called
**Bricks**. It is infrastructure, not a master LLM, planner, or source of
intelligence. Models and specialist capabilities are optional components.

## Current status

The repository contains a working Python runtime, a `.wb` ZIP-based package
format with manifest validation, connector lifecycle and capability routing,
request and streaming APIs, health/resource metadata, and a command-line
interface. The core is model-agnostic and has no mandatory third-party
dependencies. Example Bricks demonstrate request, streaming, and lifecycle
contracts; they do not provide AI inference.

White Base is runtime infrastructure, not a master LLM or a collection of
built-in AI specialists. Bricks are optional, separately installed
components. This repository contains only the White Base core and generic
example Bricks; optional model integrations and datasets are not included.
Manifest permissions and resource requests are not enforced, and
connectors execute as trusted Python code in the host process. Read
[security notes](docs/SECURITY.md) before installing Bricks.

## Install

The core runtime has no mandatory third-party Python dependencies. Python 3.10
or newer is required.

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
```

## Quick start

From the repository root, install the small Echo example and send a request:

```powershell
python whitebase_cli.py install bricks/echo.wb
python whitebase_cli.py capabilities
python whitebase_cli.py run text_generation "Hello from White Base"
```

The CLI stores installed Bricks under the current user's `.whitebase` directory
by default. Use `WhiteBase(install_dir=...)` in Python to select another
directory:

```python
from whitebase import WhiteBase

runtime = WhiteBase(install_dir="whitebase-data/bricks")
runtime.install("bricks/echo.wb")
reply = runtime.request(
    "text_generation",
    {"text": "Hello from White Base"},
    target="echo",
)
print(reply["text"])
```

The Echo Brick is a test/demo connector; it does not call an AI model.
The [Brick specification](docs/BRICK_SPEC.md) and
[development guide](docs/DEVELOPMENT.md) describe how to work with packages.

## Test

The core runtime tests do not download models or install optional AI packages:

```powershell
python -m unittest discover -s tests -p test_whitebase.py -v
python -m unittest discover -s tests -p test_architecture_contracts.py -v
python -m unittest discover -s tests/stress -p test_whitebase_stress.py -v
python -m unittest discover -s tests/performance -p test_whitebase_performance.py -v
```

## Repository layout

- `whitebase/` — runtime, package/manifest validation, protocol, and CLI.
- `bricks/` — generic example `.wb` packages for runtime validation.
- `tests/` — unit, integration, stress, and performance tests.
- `docs/` — architecture, package/protocol specifications, and security guide.

Local model weights, user datasets, virtual environments, caches, generated
outputs, and unrelated experiments are not part of this core repository.

No project license is included. Do not redistribute or reuse the project
without permission from its copyright holder.

## Security

Only install trusted Bricks. Package archive paths are validated, but the
runtime does not sandbox connector code; a connector has the host process's
permissions. Resource and permission declarations are descriptive metadata,
not enforcement. Read [SECURITY.md](SECURITY.md) before using third-party
Bricks.
