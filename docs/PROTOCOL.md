# White Base Protocol

The White Base uses a small structured message envelope for all inter-component communication.

## Message envelope

```json
{
  "message_id": "uuid",
  "request_id": "uuid",
  "session_id": "uuid",
  "source": "app",
  "target": "echo",
  "capability": "text_generation",
  "operation": "invoke",
  "data_type": "text",
  "payload": {"text": "hello"},
  "metadata": {"language": "en"},
  "timestamp": "2026-10-07T00:00:00Z",
  "correlation": {"request_id": "uuid"},
  "schema_version": "1.0"
}
```

## Core design

- request/response is supported
- streaming is supported by connectors that implement an iterator interface; unsupported streaming raises an error
- runtime events are currently in-memory text log entries, not structured messages or a persistent event bus
- connector and routing errors are raised as exceptions; they are not converted to structured error payloads
- correlation IDs help connect requests and responses

`MessageEnvelope` is a serialization container. The current runtime does not
validate envelope fields, supported data types, payload schemas, or manifest
port directions and types before dispatch.

## Supported data types

- text
- audio
- image
- video
- document
- location
- structured_data
- context
- embedding
- tool_request
- tool_result
- event
