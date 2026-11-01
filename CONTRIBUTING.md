# Contributing

## Development setup

Use Python 3.10 or newer. From the repository root:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

The core runtime uses only the Python standard library. No model weights or
large optional frameworks are required for core development.

## Validation

Run the relevant `unittest` selectors described in the README.

## Changes

- Preserve the runtime's model-agnostic boundary and `.wb` manifest contract.
- Keep generated datasets, credentials, local model weights, databases, and
  machine-specific paths out of commits.
- Update documentation when changing user-visible behavior or limitations.
- Include focused tests for behavior changes and retain existing regression
  coverage.
