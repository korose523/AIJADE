# P2-A public-reference preparation

The separately pushed [plan](../../../plans/2026-11-10-p2-a-reference-oracles.md), commit `c97638dec08db3a74d5ac6bd105f8ba5f7e5194c`, fixes all 542 tasks and two fresh-process passes before implementation. The directory date identifies that plan; execution timestamps record the actual run, including the local date crossing into 11 November. No model, verifier, generation pilot or main study runs here.

The corpus hashes retain HumanEval+ v0.1.10 (164 tasks; 124,253 base/extended inputs) and MBPP+ v0.2.0 (378 tasks; 41,015 inputs). `inputs/` contains the unchanged compressed releases; `upstream/` retains required official sources and notices. The input deserializer is compiled from its pinned function AST without running the upstream module's downloader/import initialization. Reference calls use the upstream per-call deepcopy and per-partition namespaces; returned values are retained through each partition before serialization so an aliased return object has the same final value as in the upstream helper.

Records preserve original serialized arguments, restored Python types, reference values/exceptions, comparator requirements and native base-assertion results. Unsafe integers, nonfinite floats, nonstring dict keys, sets, complex values and unsupported objects are not silently replaced by null. Unsupported type labels are not evidence of value agreement. Native assertions and reference outcomes are distinct checks. A mechanical preparation status does not certify the task description, finish a JavaScript port, choose a study task set or estimate model/verifier error rates.

`worker.py` runs only through the Mac controller's restriction profile, without service credentials or network. Artificial checks include unrelated file reads/writes and network denial, timeout retention, original type restoration, argument isolation, partition state, return-object aliasing, native assertion separation and malformed/missing input rejection. Startup initially failed before any corpus/reference record; the corrected profile permits the filesystem root directory as a literal path, not its subtree. Original failures and the correction remain in `engineering/`. This is a tested restriction boundary, not a security certification or formal Mac hardware qualification.

Execution is explicit and refuses a dirty source tree or an existing output directory:

```sh
python3 run.py --execute --qualification engineering/qualification-07/qualification.json --out /path/to/new-private-output
python3 analyze.py /path/to/new-private-output --out /path/to/summary.json
python3 verify.py /path/to/new-private-output --summary /path/to/summary.json --out /path/to/validation.json
python3 export_bank.py /path/to/new-private-output --summary /path/to/summary.json --out /path/to/new-bank
python3 -m unittest -v test_reference.py
```

The controller allows one process at a time, 15 CPU/30 wall seconds and 64 MiB output per task, with separate memory settings/monitoring and a 45-minute total limit. Every failed or partial task remains in the ledger. Analyses run no canonical program or model. The proposed bank exports statements and oracle expectations separately; it is outside the product runtime and original SkillBench fixtures. Model-facing prompts must not load the oracle file in a later study.

Corpus execution results are added only after the frozen implementation runs. Existing published runtime, configuration, research artifacts and manuscript facts remain protected.
