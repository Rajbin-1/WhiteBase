# Connector Specification

A connector mediates between the White Base protocol and a component implementation.

The connector must implement:

- `invoke(capability, payload, metadata=None)`
- `stream(capability, payload, metadata=None)` only when streaming is supported
- `health()` and `shutdown()` are optional lifecycle hooks

Connectors execute in-process. The runtime routes capability names and manages
load/unload state, but does not validate payload schemas or enforce declared
permissions, dependencies, or resource limits. Connectors should validate
component-specific inputs and raise explicit errors for unsupported operations.
