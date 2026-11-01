# Security Model

The runtime validates Brick archive paths and required manifest fields, but it
does not currently provide a sandbox or permission-approval mechanism.

## Principles

- treat Brick packages as trusted executable code
- validate Brick package paths and basic manifest requirements before installation
- reject corrupted packages
- isolate lifecycle states explicitly
- recognize that connectors execute in the host process

## Current boundary

Manifest permissions are metadata only: the runtime does not ask for approval
or restrict filesystem, process, network, or hardware access. A connector can
use the privileges of the White Base process. Do not install untrusted Bricks.

Archive path traversal and unsafe entrypoint paths are rejected, but this
package validation does not protect the host from malicious connector code.
