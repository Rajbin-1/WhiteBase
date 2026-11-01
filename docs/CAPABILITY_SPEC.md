# Capability Specification

A capability is the highest-level abstraction of White Base composition.

Examples:

- conversation
- text_generation
- speech_to_text
- text_to_speech
- image_to_text
- retrieval
- translation
- maps
- tool_execution

Capabilities are not raw model names. They describe what a component can provide.

The runtime indexes components by capability and resolves requests using deterministic rules.
