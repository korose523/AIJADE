# P3: controlled conversation history and question-recording trajectories

Date: 12 November 2026 (Asia/Seoul). Push this document alone before implementing
or executing this follow-up. The author has repeatedly authorized continued Mac
research, manuscript/evidence updates and GitHub commits. This is a prospective
local follow-up after the preceding results were known, not OSF registration or
supervisor approval. The older send-before-code instruction is not represented
as satisfied; the current handoff remains papers and a code link, with no message
sent. No new formal Ch7 held-out case or P2 model judgment is authorized here.

## Research question and actual entry

The published P3 product captures use empty supplied chat history and do not
record evaluation questions as memory. Current browser and bot callers start
ConversationRecorder asynchronously while entering SendAsync; the MCP caller
awaits recording. Those callers do not specify a distribution over interleavings.

Measure how fixed, disclosed history/recording schedules change the actual
default text memory provider's candidate-to-prompt evidence delivery. This is a
controlled script of public evaluation questions, not natural user conversations,
fact extraction, contradiction labels, default external-agent maintenance,
generated answers, emotional quality or real recipient delivery.

The product base is 7f210ee. Add instrumentation only in new research/test files
in the isolated worktree. Do not change production sources, the 331 earlier
protected files, historical captures, scorers, helpers or numerical facts.
Use actual CompanionRuntime.Create / ChatOrchestrator.SendAsync,
MemoryRecallProvider(maxItems=5), ConversationRecorder and API chat persistence.
No companion/life/tool modules are enabled. Use the default 24-message history
window and PromptBudget (module 4,000, supplements 12,000, history 24,000 UTF-16
units), with audio off. A local recording transport captures complete requests
and returns the same visible reply "ok"; no chat or embedding model is called.
Nothing uses the expected answer to construct a runtime input.

## Fixed inputs, trajectories and schedules

Use the already available LoCoMo ACL 2024 corpus:
SHA-256 79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4.
All ten conversations and all 1,986 questions run, including non-primary ones.
Retain original question order within each conversation, without outcome-driven
selection or new seeds. Five separate, freshly API-ingested databases are used
per conversation, with the same original memory text, IDs and corpus timestamps.
Rotate the order of the five independent trajectories by conversation index.
Run exactly one complete script per trajectory, serially: 50 planned trajectories
and 9,930 planned completion captures.

- static: supplied history empty; no question perceptions.
- history: actual prior messages fetched through MessagesAsync; no question perceptions.
- record-after: same history; record the current question only after SendAsync
  has completed and the completion request was captured.
- record-before: same history; await the current question's actual recorder call
  before SendAsync begins.
- record-between: same history; after the first memory GET has returned, capture
  its full response and actual SQL candidate state, then await the recorder
  before allowing the response back to the provider. Later fallback queries can
  see the new item. Record even when no fallback happens.

All three recording arms have exactly the same logical question contents and
creation timestamps after each completed turn. The current question is written
exactly once, through ConversationRecorder. Its clock is fixed to
2026-11-12T00:00:00Z plus one minute per question, so all added items are newer
than the source conversation. Real HTTP/monotonic times separately prove
execution order. UUIDs remain real and are mapped to logical question indices;
do not replace actual database writes or timestamps. Prior assistant messages
are the fixed stand-in, not ground-truth answers, and are not memory perceptions.

These are three selected interleavings, not every possible race and not a bound
or probability distribution over browser/bot scheduling. History is a controlled
script of benchmark questions and fixed replies. Never call it an evaluated
real-life interaction or a measurement of all Web/QQ functionality.

## Measures, populations and comparisons

Audit the input frame before execution: all 1,540 answerable questions and the
subset with source evidence annotations (previous frame: 1,536). Record every
missing annotation and unlocated evidence ID; no missing outcome becomes zero.
The evidence-fraction estimand is defined on the fixed annotated-answerable
frame. Also report all-answerable coverage and conservative full-frame bounds
for missing annotation/location or source ambiguity. All-question and
fully-located views are sensitivity frames, with denominators explicit.

Per turn retain source evidence IDs, actual stores and question-write deltas,
native candidate IDs/times for every actual query, raw API responses, echo
removal, selected newest five, complete prompt body and observed memory block,
supplied/used history, budgets, truncation, failed/short/empty/fallback responses,
observer errors, actual user/assistant appends and record timing. Record default
SQL ILIKE semantics rather than silently substituting a substring scorer.
No source ID is credited merely because a question mentions a fact.

Primary delivery stages are eligible full native-query union, API response
union, response union after echo removal, client selected five and complete
memory items visible in the captured first system message. History visibility
is reported separately from that memory-block recall; neither is model use.
Duplicate/unexplained blocks retain source uncertainty. Native created-time ties
are observed; response order is not made deterministic by changing SQL. Report
cutoff-tie counts and a no-cutoff-tie sensitivity frame rather than attributing
all response differences solely to the schedule.

Four paired primary contrasts of actual-prompt evidence recall:
1. history minus static (supplied-history contrast with unchanged memory);
2. record-after minus history (previous-question recording, with same script history);
3. record-before minus record-after (current-write-before-recall schedule);
4. record-between minus record-after (write after whole-query response schedule).
The last two compare logically matched prior stores; the first two are the
declared cumulative-script contrasts. Do not call these representative user
effects, or use selected hit-only denominators.

Report conversation means and differences, with complete per-question records.
For point-identified contrasts use 10,000 shared randrange conversation-bootstrap
resamples, seed 20261112, interpolated percentiles, and exact two-sided sign flips
over 1,024 conversation sign patterns; retain zero differences and apply Holm
over these four tests. Assumptions of independent dialogue units and null sign
symmetry are explicit; there are ten dialogue units, not 9,930 independent users.
For non-point-identified contrasts give the lower/upper identification bounds and
their descriptive resampling envelopes, with p null; do not turn an observer
interval into an ordinary confidence interval or borrow a point estimate.

## Qualification, resource admission and one attempt

Before corpus execution qualify the five schedules on synthetic API/database
fixtures, covering history, duplicate/echo text, fallback, exact callback timing,
one recorder invocation and provider silence. The instrument records failures;
a fixture passing is not a corpus result. Build and run the appropriate full
regression from the clean committed implementation, retaining logs and generated
assembly revision. Freeze every used DLL and new/unchanged source hash before
admission. Do not make numerical-result agreement a runtime assertion.

Use one non-resettable 120-second idle window sampled at <=2-second intervals:
all samples >=4 GiB available RAM, swap-used range <=64 MiB, no dotnet/Godot/Ollama
process. If not admitted, preserve the window and do not start/reset this attempt.
After admission run one serial .NET process with two processors. Stop at 3,600
seconds wall, or owned RSS >2 GiB, available RAM <3 GiB, or global swap growth
>1 GiB sustained 30 seconds. No unrelated process termination, cache purge,
resource-limit relaxation, parallel models/browser/research jobs or paid compute.

Exactly one corpus attempt is authorized by this plan. A stop preserves every
completed/in-flight/unattempted trajectory, raw gzip footer status, owned PID exit
and database cleanup receipt. No automatic repeat, prefix merge or zero-error
inference from missing data. Diagnose before a prospective amendment.

## Audit, publication and paper updates

Independent Python reconstruction checks every scheduled key, source/corpus and
clean-build identities, store deltas and cross-arm logical state parity, API/query
provenance, callback chronology, history assembly, UTF-16 budgets, complete item
attribution and denominators. Numerical aggregation must be separately checked.
Disposable corruptions must reject omitted turns/arms, an omitted or duplicate
question write, swapped timing, edited history, changed query/response/selection,
hidden ambiguity, a different corpus and source/hash/closure changes. Preserve
the primary bytes. Unfavorable or zero differences remain reportable.

Archive all decision-relevant records with logical and compressed byte hashes;
use lossless chunking if needed. Corpus-derived text retains the upstream
CC BY-NC 4.0 license, not the code license. Do not bundle models or private chats.
Public plan order is not external preregistration or mentor receipt.

After actual complete audit, add the new configured results and limitations to
P3 English/Chinese and the dissertation, preserve all older facts/study versions,
update data/code availability, rebuild final PDFs and inspect selected pages.
Keep default fact extraction, genuine contradiction/staleness quality, full
Web/QQ behavior, model answers, formal Mac eligibility, P2 new judgments/larger
model, new Ch7 held-out protocol/execution, independent human review and final
author/supervisor/CAS confirmation open. Deliver papers and code link only.
