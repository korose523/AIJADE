# Native lifecycle unification final engineering receipt

Current source is ready for parent integration; no real observer, native census, API, qualification, renderer or model was called by this work. Candidate Q1 `61a335c297f60d0b258c92d73ad5c20573cc4c24` remains an unexecuted candidate with a native lifecycle omission. A new Q/B is required.

45 controls passed: 22 serialized guard controls, 18 managed-process/cleanup controls, and 5 fake-native/pipe controls. Original failures 01, 02, 04 and 07 and their candidate snapshots remain intact. Native timeout stays 0.5 seconds; the flaky cold-exec output-cap test was split into a deterministic pipe cap control, while actual disposable C registration, timeout and refused-ready controls remain separate.

The fixed 4,322-event synthetic journal replay measured a maximum 0.364704 seconds for one full guard and 0.672997 seconds for two full replays. This is parser CPU evidence; it is not a live 2.5-second budget or capacity guarantee.

`cleanup_refused` snapshots actual refused handles and returns exactly the same ordered attempt population. It never clears refusal, creates a process, samples the host, or signals an unrelated group. Parent controls when it runs and binds the cleanup receipt.

The JSON receipt binds exact final source/test hashes, preserved historical byte comparisons, control logs and adverse candidates.
