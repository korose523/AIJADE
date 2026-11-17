# Portable native integration controls

This directory is a private test-publication preparation only. No production W5 file was changed. The eight publish files are listed with exact target paths and SHA256 in `publishing-path-manifest.json`. Root must copy only those files after checking the manifest, then execute them on the actual W5 checkout before committing.

The actual local run used `verification-repo`, a bounded, normal-layout mirror of 24 current W5 source files plus five existing test helpers. Its exact source map is retained. It was not a full-tree copy, a new engineering window, or a backend/scientific qualification. All test fixture outputs stayed inside AIJADE.

- Integration: 45/45, no skipped tests. Every original test name and assertion AST is preserved. Only source-root/scratch resolution, the historical-test path, and the default fabricated logical source origin were adapted. Test 39 still uses the original archived logical paths and verifies that records/policy/raw bytes are not rewritten.
- Pure listener: 65/65, no skipped tests. Every original method and assertion is unchanged. The header resolves sources relative to the checkout and verifies the exact frozen oracle source.
- Native gate/Registry: 20/20, no skipped tests. The original portable test file is byte-for-byte unchanged. These tests compile AIJADE's native C source and run self-contained gate/echo fixture processes with actual waits and cleanup. They never invoke lsof, API, model or renderer queries.
- Additional source-binding controls: one positive and three corruption refusals (full source byte, oracle byte, binding SHA). These four offline controls are separately reported, not folded into the 130 inherited controls.

The frozen e918 source comes from the public E5 packet source tree and retains full SHA e918de7431e3f27af2e03017a2f504bf00d85a6a08bf05d7ba5fcd3e14291035. The historical full module is never imported or executed: the binding helper hashes it and compares exact extracted `_read_listeners` function bytes with the adjacent mock-only oracle. Both integration and pure suites reject a missing or changed binding/source; there is no private research-path fallback.

`pure_listener_fixtures.py` is the original unchanged fabricated-data helper; its name does not match `test_*.py` and it is not counted as a second 65-test suite. Existing helper files remain in `tests/shell` and are not replaced. The 34-item historical runtime golden population remains unchanged; current-source integration correctly requires 33 original functions plus the separately versioned online factory change, and separately controls setup dispatch.

CI commands (from checkout root, using the existing psutil==7.2.2 finite-control-env):

```sh
.runtime/finite-control-env/bin/python -B -m unittest discover -s tests/shell -p 'test_native_integration.py' -v
.runtime/finite-control-env/bin/python -B -m unittest discover -s tests/shell -p 'test_listener_evidence.py' -v
.runtime/finite-control-env/bin/python -B -m unittest discover -s tests/shell -p 'test_native_exec_registry.py' -v
```

CI should require an existing clang or cc before Native20; a skipped Native suite is not 20 passes. No dependency installation or workflow edits were performed by this preparation. Native test scratch defaults to `<checkout>/.runtime/native-exec-controls`; integration scratch defaults to `<checkout>/.runtime/native-integration-controls`. On the Mac's external NTFS project directory, use the existing APFS scratch override `AIJADE_NATIVE_TEST_SCRATCH=/Volumes/Untitled/AIJADE/.runtime/posix/tmp/native-ready-portable-controls`. The logical paths in fabricated native proofs intentionally stay under the frozen lifecycle BASE even on Linux, while physical source authentication uses the actual colocated checkout bytes. This preserves archived path semantics without reading fake logical files.

Original private test source, original datasets, every local log and exact portability diffs are retained. No prior refusal record, production source, scientific gate, Git state or published packet was changed. All tool processes used here exited; no live observer or global listener query was started.
