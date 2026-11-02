# White Base — Core Runtime Audit Fixes Report

**Date:** 2026-11-02  
**Branch:** `fix/runtime-audit-issues`  
**Base Commit:** `0c15599` (*Fix core runtime reliability and release hygiene*)  
**Repository:** `https://github.com/Rajbin-1/WhiteBase.git`

---

## 1. Confirmed Findings

1. **Brick Loading:**
   - Dynamically loaded Brick modules failed sibling-module imports unless their directory was added to `sys.path`.
   - Dataclass connectors using `from __future__ import annotations` failed with `AttributeError` during dataclass definition if the module was not pre-registered in `sys.modules`.
   - Dynamic modules without brick-scoped naming could collide across bricks.
   - Modules remained in `sys.modules` on unload or load failure.
2. **Execution Timeouts:**
   - Previous timeout checks evaluated elapsed time only after the synchronous call returned, unable to stop hung execution.
   - Non-isolated in-process connectors could not be forcibly terminated.
3. **Streaming Lifecycle:**
   - Raw generator/iterator returns bypassed `active_requests` tracking, allowing concurrent `unload()` while clients were reading streams and failing to track streaming request metrics.
4. **Discovery and Routing Robustness:**
   - Leftover staging/backup directories (`.staging-*`, `.backup-*`) could pollute discovery.
   - Capability indexing could append duplicate provider entries upon package reinstall.
   - Tied provider priorities could result in arbitrary selection rather than strict ambiguity detection.
   - Discovery failures in invalid packages were silently ignored.
5. **Manifest & Archive Validation:**
   - `format_version` was not verified against supported major versions.
   - Declared checksums were silently overwritten with local file hash rather than verifying actual package contents.
   - Port direction and specification types were not strictly validated.
   - Archive entries with null bytes or directory traversal were not completely validated.

---

## 2. Fixes & Files Changed

### `whitebase/connector.py`
- Added `_subprocess_invoke_worker` and multiprocessing-based isolated execution in `BrickConnector.invoke(..., timeout=...)`.
- When `timeout` is specified, launches an isolated worker via `multiprocessing.Process` with IPC pipe communication. If execution exceeds the deadline, the child process is terminated (`proc.terminate()` / `proc.kill()`) and resources are cleaned up.

### `whitebase/runtime.py`
- **Brick Loading & Cleanup:**
  - Added safe brick directory insertion into `sys.path` during import, safely removed in a `finally` block.
  - Pre-registers `whitebase_brick_{safe_id}` in `sys.modules` before `exec_module`.
  - Cleans up `sys.modules` entry upon `unload()` and on load failure.
- **Streaming Lifecycle Management:**
  - Wrapped `stream_request()` in a managed generator (`_managed_stream`) that increments `active_requests` and `runtime_metrics["active_requests"]` on entry.
  - Prevents `unload()` during active stream consumption by enforcing the active request lock.
  - Releases active request counters, updates success/latency metrics, and records error states on generator completion, cancellation, or exception.
- **Discovery & Routing Hardening:**
  - Filters out hidden temporary/backup directories (`.staging-*`, `.backup-*`) in `_discover_installed`.
  - Records non-hidden discovery directory/package failures in `self.discovery_errors` and emits log warnings/errors.
  - De-duplicates capability provider indexing.
  - Strictly detects ties in provider ranking (`is_default`, `priority`) and raises `AmbiguousRoutingError` unless an explicit target is specified.

### `whitebase/manifest.py`
- Enforces `SUPPORTED_FORMAT_MAJOR_VERSIONS = {1}` on `format_version`.
- Rejects null bytes in archive member paths (`\x00`).
- Validates declared manifest checksums against actual archive contents (`connector.py` and manifest) upon archive validation.
- Preserves declared manifest checksums on disk during `load_manifest()` rather than overwriting them.

---

## 3. Regression Tests Added

In `tests/test_audited_defects.py`:
- `test_multi_file_and_sibling_module_imports`: Confirms sibling imports within package directory resolve correctly.
- `test_dataclass_connector_with_future_annotations`: Validates dataclass connector execution with postponed annotations.
- `test_module_name_isolation_between_bricks`: Verifies distinct bricks do not collide in module namespace.
- `test_sys_modules_cleaned_up_on_unload_and_load_failure`: Verifies `sys.modules` state is restored on unload and on failed load.
- `test_real_timeout_terminates_execution`: Proves hung connector execution terminates within timeout deadline.
- `test_streaming_tracks_active_requests_and_prevents_unload`: Tests `active_requests` counter, prevents unload during active streaming, and releases state upon stream completion.
- `test_streaming_error_releases_active_requests`: Tests that exceptions during streaming cleanly release active requests and record failure state.
- `test_unsupported_format_major_version_rejected`: Rejects major version bumps (e.g. `2.0`).
- `test_manifest_invalid_port_direction_rejected`: Rejects invalid port direction values.
- `test_manifest_checksum_verification_failure`: Fails installation when package content doesn't match declared checksum.
- `test_discovery_ignores_stale_staging_and_backup_dirs`: Verifies hidden staging/backup directories are ignored by discovery.
- `test_discovery_exposes_failures_for_corrupt_unhidden_directories`: Verifies corrupted directories are captured in `discovery_errors`.
- `test_reinstall_does_not_duplicate_capability_registration`: Verifies capability index remains clean across reinstalls.
- `test_ambiguous_routing_raises_error_when_no_priority_or_default`: Confirms ambiguous routing error when multiple providers lack ranking.
- `test_ambiguous_routing_raises_error_on_tied_priorities`: Confirms error when multiple providers have equal non-zero priority.
- `test_provider_selection_respects_priority_and_default_metadata`: Confirms deterministic provider selection based on priority.

---

## 4. Exact Commands & Real Results

1. **Unit and Contract Suite:**
   ```powershell
   python -m unittest tests/test_whitebase.py -v
   python -m unittest tests/test_architecture_contracts.py -v
   python -m unittest tests/test_audited_defects.py -v
   ```
   *Result:* 9 + 13 + 16 = 38 passed, 0 failed.

2. **Stress & Performance Suites:**
   ```powershell
   python -m unittest discover -s tests/stress -p "test_whitebase_stress.py" -v
   python -m unittest discover -s tests/performance -p "test_whitebase_performance.py" -v
   ```
   *Result:* 6 stress tests passed, 3 performance tests passed. Total: 47 passed, 0 failed.

3. **Packaging Build & Twine Check:**
   ```powershell
   pyproject-build
   twine check dist/*
   ```
   *Result:* Built `whitebase-0.1.0-py3-none-any.whl` and `whitebase-0.1.0.tar.gz`. Both PASSED twine check.

4. **Clean Virtual Environment Smoke Test:**
   - Created temporary isolated virtual environment.
   - Installed `dist/whitebase-0.1.0-py3-none-any.whl`.
   - Verified `whitebase --help`.
   - Executed demo Echo Brick workflow via `WhiteBase.install('bricks/echo.wb')` and `request()`.
   *Result:* Exit code 0, demo echoed successfully.

---

## 5. Remaining Limitations & Unverified Platforms

1. **In-Process vs. Subprocess Execution Boundary:**
   - Standard requests without a timeout parameter execute in-process for low overhead.
   - Subprocess isolation is triggered when a timeout is specified to guarantee execution termination.
   - Connectors containing unpicklable handles (e.g. open system hardware handles) must be invoked without timeout isolation or implement custom IPC protocols.
2. **Platform Verification:**
   - Verified locally on Windows (Windows 11, Python 3.13 spawn method).
   - Linux and macOS CI matrix configurations are set up in `.github/workflows/ci.yml`.
