# Benchmarks

White Base should be measured as infrastructure overhead, not as an AI model.

## Minimal benchmark set

- empty runtime startup
- idle memory footprint
- registration overhead
- single request latency
- 1000-message throughput
- load/unload overhead
- streaming overhead

A practical benchmark is intentionally built around mock components so that the runtime overhead is isolated from model inference cost.
