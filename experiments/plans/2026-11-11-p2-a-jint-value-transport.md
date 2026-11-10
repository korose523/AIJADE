# P2-A Jint value transport correction

11 November 2026 (Asia/Seoul). The development replay found that Jint's string iterator groups some Unicode code points and CRLF sequences. The port will enumerate UTF-16 surrogate pairs explicitly so source algorithms that require Python code points receive the declared sequence. Retain the mismatches from the development run.

Jint rejected BigInt exponentiation for seven `HumanEval/83` cases under its size guard. This task will return exact decimal digit strings throughout. Before accepting the projection, verify every typed released integer against the exact counting formula and bind the projected string to the original case. A result containing a different digit, a different length or a different value type fails comparison. Keep the Jint limits and the original BigInt attempt in the evidence. The port specification states the decimal string return type.

Optimize the implementations that timed out using their statement algorithms and rerun the full released population. The final replay preserves the existing per-call, process and memory limits. Its report includes any remaining unmatched or unavailable cases.
