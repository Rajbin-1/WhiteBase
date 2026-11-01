# White Base Architecture

## Layering

```text
Application
    ↓
White Base Runtime
    ↓
Capability / Connector Layer
    └── Independently installed Bricks (generic examples included here)
```

The White Base has no domain intelligence. It provides lifecycle and routing infrastructure.

## Implemented runtime responsibilities

- Install `.wb` ZIP packages after archive-path and required manifest-field
  validation.
- Discover and register capabilities, then route requests to a selected Brick.
- Manage connector load/unload lifecycle and expose health/resource metadata.
- Support synchronous requests and connector-provided streaming.
- Maintain in-memory runtime events and request metrics.

Manifest port schemas and message-envelope semantics are not fully validated
during routing. Permission declarations do not create a sandbox, and
resource/dependency metadata is not checked against the host.

## Components

Every installed component is a Brick and declares capabilities and ports.
This repository includes generic example Bricks for validating the runtime
contract; they do not call AI models. Model-backed capabilities, specialist
implementations, and connectors are optional separately managed packages, not
part of this core distribution.

## Connector boundary

A connector adapts the White Base protocol to a component-specific implementation.

The core runtime does not import model-specific logic.

## Data flow

```text
client request
    ↓
White Base
    ↓
capability lookup
    ↓
selected component
    ↓
connector.invoke()
    ↓
structured result
    ↓
response or streaming chunks
```

These design choices keep the runtime small and composable.
