# Offline E6 journal prefix comparison

The retained engineering attempt ended during settling. This comparison
measures one suggested processing change using the archived journal. It makes
no runtime policy change.

The existing producer authenticates the complete old prefix with a bytes
slice and equality. On a growing journal the slice copies the old prefix.
The alternative uses `bytes.startswith` on the same bytes. Equal-length
inputs use independent buffers so that both comparisons need to inspect the
bytes. Both retain exact equality and reject shortened, rewritten, or
incorrectly typed inputs. The original event parser continues to validate
the tail after a prefix match.

The [recorded plan](prefix-comparison-plan.json) fixes the input hashes,
four selected cutoffs, and within-condition order before measuring. The
[result](prefix-comparison.json) contains all 384 timings. The producer
source is pinned to the E6 bytes. The benchmark authenticated all 169
recorded cutoffs, and incremental and cold replay agreed field by field,
including types and container order, at the four selected points. The
adverse checks include rewrites at the first, middle and last old-prefix
byte, a legal earlier cutoff, a wrong input type and a malformed event tail.

| E6 observation index (zero-based) | Full cutoff (bytes) | Growing prefix paired median savings (ms) | Equal length paired median savings (ms) |
| --- | ---: | ---: | ---: |
| 0 | 6,230,214 | 0.416 | 0.004 |
| 83 | 7,046,247 | 1.370 | 0.005 |
| 166 | 7,862,303 | 1.731 | <0.001 in favor of slicing |
| 167 | 7,872,136 | 1.728 | 0.007 |

The timed calls cover in-memory prefix matching in one process. The
unchanged parser, filesystem reads, durability barriers, native process
collection and shared-lock concurrency are outside those timings. The
milliseconds of local savings do not predict whether the next complete
listener call will meet its 0.5-second deadline. The
[retained E6 record](../native-ready-2026-11-18/README.md) and its engineering
disposition remain the basis for Chapter 7. Backend qualification and
the approved 40-pair comparison are still pending.

The [17 November scope correction](../heldout-scope-correction-20261117.json)
records the supervisor's permission for the 40-pair design and the need to
review the new qualification criteria before another run. This journal
component comparison does not set the revised qualification criteria.

Run the [benchmark](../benchmark_producer_prefix.py) with the retained
original journal, initialization record, and independent cold audit cutoff
export, using `--journal`, `--initialization`, and `--cold-details`.
Pass this directory's plan using `--plan` and a fresh `--output` path.
The source and inputs must match their recorded SHA256s. A reproduction
checks their semantics and produces its own host timing record.
