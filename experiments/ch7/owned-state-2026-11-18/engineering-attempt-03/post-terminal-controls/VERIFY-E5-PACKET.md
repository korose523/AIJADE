# E5 refused engineering record: read-only verification

Use Python 3.9 or later with the four normal modules in this directory:
`verify_e5_packet.py`, `packet_common.py`, `e5_refusal_semantics.py`, and
`lossless_members.py`. The entry point was actually verified using macOS
Python 3.9.6. It requires only the standard library.

```sh
python3 -B verify_e5_packet.py --packet /absolute/path/to/packet
```

The v2 physical manifest covers every envelope, member and direct file.
`logicalFiles` also binds each complete original logical byte sequence,
including the zero-byte admission log. Each gzip member decodes at most
16 MiB; complete logical bodies are never truncated or replaced by summaries.
Original raw bodies, all 48 fixed Git source bodies, separate independent
negative cold-audit outputs and the source-bound root disposition are retained.
The complete packet has 774 physical payloads and 414 logical files, including
356 mappings to selected original artifacts. The manifest itself is excluded
from its payload table and must be anchored separately:

- Manifest SHA256: `0c0338bfa3b2b8862cf4e5aff4aae3baa28b1ede8a9ad0c5ab8e9a238a51b83e`
- Summary SHA256: `7b16c72c9f174eb695ff64c24457c99e57580f942029b6de1af5a90b034635ea`

The portable tool rechecks transport completeness and reconstructs all 55
reported typed values, all 174 retained raw records and the actual per-owner
callback populations. It does not execute the archived Python 3.12 observer,
recompute its AST on Python 3.9, rerun the kernel cold audit, or provide a new
backend/scientific certificate. The original cold audit and full typed decision
export remain separately hash-bound evidence.

This attempt remains refused: 173 raw/stream decisions passed, and the last
raw decision was UNKNOWN with unknown RSS and a refused stream validation.
The outer cursor short-circuited before its last evaluation. All 174 complete
service clocks stayed below two seconds. There was no admission, child block,
formal backend qualification, model inference, seed or held-out comparison.
The listener cause remains `UNRESOLVED_OR`; the original provisional statement
and its explicit precision correction are both retained.

Fourteen original copied-baseline adverse controls and one additional
fictitious final outer-call control are executed separately from this record.
Their final receipt states the exact source and actual execution populations.
Original packet bytes and historical P4/E3/E4 refusals remain immutable.
