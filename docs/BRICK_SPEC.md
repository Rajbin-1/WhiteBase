# Brick Specification

A White Base Brick is a package with a manifest and a connector implementation.

## Package format

A Brick is distributed as a `.wb` ZIP archive containing:

- `manifest.json`
- `connector.py`
- `README.md`
- optional resources or schemas

## Manifest schema

The manifest must declare:

- format and version
- id and name
- semantic version
- capabilities
- ports
- runtime metadata
- resource metadata
- entrypoint location
- dependencies and permissions
- metadata and compatibility hints

Packages are checked for safe archive paths, a valid ZIP structure, a manifest,
and a packaged entrypoint before installation. Manifest validation currently
checks required top-level fields and basic port names; it does not validate
port schemas, dependencies, permissions, or host resource compatibility.
