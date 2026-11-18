# Multi-turn dialogue and Live2D browser validation

A single in-page monotonic clock now controls the duration and periodic samples. An early stop leaves the observer running. The terminal endpoint is retained separately from the periodic sample census. The prior 1799.9879 s result failed its 1800 s gate by approximately 12.1 ms and remains in this package.

The final local Chrome session measured **1800.023400 s** using the published clock. It presented 53,794 frames and collected 181 neutral face samples. The largest strong-red ratio was 2.61% against an 11% ceiling. There were zero WebGL context losses or model releases during the measurement and 11 completed WAV/playback/native-mouth checks across the ordinary browser trajectory. The paired short preflight and full run used the same actual Qwen2.5-Coder 1.5B and macOS Tingting services, and the same pinned server and served WebAssembly bytes. The browser report preserves the model's cue adherence and the separate literal expression check. After the measurement, the explicit JSON path returned and stored the exact bare value with one non-streaming model call and zero speech or render events.

## Missing dialogue baseline

Reconstructed requests for the shared-interest scenario reproduced marker-only HTTP 200 responses for both original seeds. The six subsequent baseline turns stayed censored. The historical comparison therefore remains 16/24 pairs complete. A separately frozen supplemental comparison reused the four target user turns and added the same two-message synthetic starting history to both arms. It completed 8/8 matched pairs. Exact opener repeats were 1 in each arm, fixed-pattern counts were 0 in each arm and question endings were 2 versus 0. The original and supplemental denominators are reported independently.

## Prompt comparisons

| Candidate | Matched pairs | Repeated openings, shipped → candidate | Fixed-pattern turns, shipped → candidate | Decision |
| --- | ---: | ---: | ---: | --- |
| 1 | 24/24 | 7 → 8 | 2 → 0 | Rejected |
| 2 | 24/24 | 6 → 4 | 2 → 2 | Rejected |
| 3 | 24/24 | 7 → 5 | 2 → 4 | Rejected |

All three candidates were screened with the same model, two seeds and three synthetic dialogue scenarios. Each reused the same target cases. Candidate 1 increased repeats. Candidate 2 missed its boundary-scenario opening criterion. Candidate 3 increased fixed-pattern hits. Production keeps the previously shipped prompt. The audit includes each refusal and raw-ledger hash. The replay protocol contains synthetic fixtures and prompt settings. The browser and voice checks exercise the actual Web flow with the retained prompt.

This package records local product engineering and automatic diagnostics on synthetic dialogue. Manuscript evidence and formal research approvals have their own records. Raw provider replies, audio, browser captures and third-party avatar assets are retained locally.
