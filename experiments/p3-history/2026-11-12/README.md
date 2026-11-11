# Controlled history and question-recording follow-up

The prospective local plan is
[`2026-11-12-p3-history-question-recording.md`](../../plans/2026-11-12-p3-history-question-recording.md).
It was pushed separately before these instrumentation files. This is not external
preregistration, supervisor approval, natural conversation or answer evaluation.

`input_frame.py` independently projects the fixed public LoCoMo source without
expected answers. `eligibility.py` obtains native PostgreSQL ILIKE eligibility in
temporary tables, including possible question texts; future entries are excluded
per audited recording chronology. Neither projection is a measured product run.
The original corpus is not required in CI: the answer-free, hashed projection and
the native oracle are retained. `run.py` requires the exact original local corpus,
clean committed binaries, a build/qualification freeze and the fixed admission.

`audit.py` reconstructs source writes, query states, schedules, history, complete
requests and UTF-16 budgets. `analyze.py` reports the four planned paired contrasts
with ten dialogue units and explicit identification bounds. `check_aggregation.py`
uses separate sums and sign enumeration. `test_rejections.py` uses disposable
corruptions, leaving primary records unchanged. Research output is opt-in and
never part of the normal full regression. No external chat/embedding model is used.

## Data license

`input-frame.json.gz`, `eligibility-oracle.json.gz` and any archived corpus-derived
text remain derived from the LoCoMo dataset, copyright its original authors,
under **Creative Commons Attribution-NonCommercial 4.0 International**:
<https://creativecommons.org/licenses/by-nc/4.0/>.
Source: <https://github.com/snap-research/locomo>, the ACL 2024 LoCoMo benchmark.
The repository's software license does not override this data license. No models,
private chats or credentials belong in this evidence packet. This experiment's
scripts and new test instrumentation follow the repository's software license.

The experimental-design workflow was assisted by the installed Scientific Agent
Skills experimental-design skill; the project's existing workflow attribution
applies. Passing engineering checks is not independent human or scientific review.
