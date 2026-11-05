# P3-E: How many relevant memories reach the prompt on the product's own path?

**Status.** Committed to this repository on its own on 5 November 2026, before its code. It is not registered on an external platform. By the first author's decision of 5 November 2026 it runs on the Mac before the supervisor's review: the embedding model is the first author's proposal, not a value the supervisor has agreed, and the plan was not sent to the supervisor before its code was written.
*Last revised: 3 November 2026; checked again on 4 November 2026. Code statements checked against commit `97aab7c` of the code repository.*
*Revisions: 27 October 2026 (added at the supervisor's request: the dissertation studies an AI companion, and the research kernel of the paper is not used by the product server, so the product's delivery path is measured as well); 3 November 2026 (supervisor's review: a primary measure, a comparison arm for the client's reordering, the items counted in the prompt defined, the cases counted separately, and the measured commit and entry path fixed, since the prompt is assembled in a file outside the two frozen ones).*

## Study information

**Research question.** On the path that delivers memories into the model's prompt in the product, how much of the evidence for a question is lost, and at which step?

**Background (from the code at the registered commit).** The product client (`src/Aijade.Client/Chat/MemoryContext.cs`) asks the server for `maxItems + 1` = 6 memory items for the whole utterance (`maxItems` is 5 where the chat page, the bot bridge and the MCP server construct it) and drops items whose text equals the utterance; only if none remain does it search once for each of the three longest distinct words of three or more letters or digits. It then orders the received items by creation time and puts the five most recent into the prompt. The server's memory library (`src/Aijade.Server/Memory/MemoryLibrary.cs`) returns only items of sessions the caller owns. When an embedding route is configured it takes the caller's 2,000 most recent items, ranks them by cosine similarity plus 0.15 for an item that contains the query verbatim, and drops those below 0.3; otherwise, or if embedding fails, it returns the items that contain the query as a case-insensitive substring, newest first. The text path therefore ranks by recency alone, and the client reorders by time and truncates within whatever it receives. Every recorded perception is stored as an evidence pack and chunk whether or not the pipeline's gate commits a memory version (`src/Aijade.Server/V9/V9RuntimeStore.cs`), and the library reads those packs, so the gate itself drops no turn; turns lost at writing for any other reason are counted (Data exclusion).

**Hypotheses.** None directional. The study reports the loss at each step whatever it is.

## Design plan

**Study type.** Diagnostic measurement on the author's own software, on a public corpus. No download is needed for the text path; the embedding path needs a local embedding model (permission required).

**Entry path and measured commit (fixed now).** The measured path is one product chat turn: each question is sent as the user's message through `ChatOrchestrator.SendAsync` (`src/Aijade.Client/Chat/Orchestrator.cs`) in a chat of the conversation's user, with the product's default settings (memory module on, `MemoryRecallProvider` with 5 items as the chat page constructs it, no stage or reminder notes), and the assembled prompt is captured at the model call by a local stand-in endpoint that records the request and returns a fixed reply, so no model is called. The prompt is assembled in `Orchestrator.cs`, outside the two frozen files below, and that file has changed since they were frozen (the system notes placed right before the user's message, and the proactive lines that do not consult the context providers), so the product code is fixed by commit: it is that of the commit on which this plan is pushed, run from an isolated checkout of that commit with the study's harness added in files the product does not use. The results file records both commits. Every user turn consults the memory provider, the first turn of a chat included; her proactive lines (speaking first and reminders) consult no provider, deliver no memories and are outside the measured path.

**Procedure.** LoCoMo conversations are written into an isolated product store through the product's own write path, for one user per conversation. Each turn is posted as a perception the way Chapter 6's loader (`src/Aijade.Memory/Locomo/Locomo.cs`) encodes it: the turn's text as the content, without the speaker (the product stores text only), and the session's date and time plus one minute per turn as its timestamp, so that creation order is turn order; turns without text are skipped and counted. For each question, the path is recorded step by step: the candidate pool, its ranking, the filters, the server's response and the client's processing up to the prompt. The product's ownership filters are not bypassed. Product code stays in maintenance under the project's scope decision (`docs/decisions/ADR-001.md`); any instrumentation it needs is recorded as an exception before it is made, and does not change what the product delivers. The client and server files of this path (`src/Aijade.Client/Chat/MemoryContext.cs`, `src/Aijade.Server/Memory/MemoryLibrary.cs`) are listed as research objects in `configs/project-scope.json` since 28 October 2026 and are not changed before this study is run and archived; a change made anyway is reported as a deviation.

**Conditions.** Server retrieval by text and by embedding, through the product's gateway route to a local Ollama serving `nomic-embed-text` (digest `0a109f422b47`, the same vectors source as P3-D). The product sends the texts with no task prefix, and the study keeps that.

**Comparison arm for the client's reordering (fixed now).** Within the candidates that have passed the same filters (the server's response after the client has dropped the utterance's echo, together with the term searches when they run), the top five in the server's order (similarity on the embedding path, newest first on the text path) are compared with the top five by recency, the client's rule. On the text path the two orders coincide, which is reported as such; the arm matters mainly for the embedding path.

## Sampling plan

**Existing data.** LoCoMo (ACL 2024 release, SHA-256 checked before every run). The 1,540 answerable questions are primary; all 1,986 are reported alongside. **Sample size.** All 10 conversations; the conversation is the unit of resampling.

## Variables

**Primary measure.** On the fixed question set (the 1,540 answerable questions), the evidence recall at each stage of the path, namely the candidate pool, after ranking, after filtering, the server's response and the prompt (per question, the share of its evidence turns present; averaged over the questions of a conversation, then over the conversations), and the differences between consecutive stages, the loss at each step, each with a conversation bootstrap interval. The loss from the candidate pool to the prompt is the primary quantity; the steps are its decomposition.

**Measured.** Per question: whether at least one evidence turn, and what share of the evidence turns, is present at each stage; in the two arms of the comparison above, the same for their top five; among the items in the prompt, the number newer than the question's newest evidence turn (counted as in Chapter 6) and the number whose text repeats another prompt item (whether an item contradicts the evidence is not measured, as the corpus does not label it); time and calls per question. Counted separately and reported with their questions: empty server responses, responses with fewer than five items after the echo is dropped, turns in which the term searches ran, and turns in which the memory provider was not consulted.

## Analysis plan

**Statistical models.** Conversation bootstrap (10,000 resamples, percentile 95%) for each step's recall and for the loss between consecutive steps.

**Inference criteria.** The results describe retrieval along this path; with no reader or answer evaluation fixed, they are not extended to answer accuracy. A path that loses no evidence is reported in the same detail.

**Data exclusion and missing data.** Questions whose evidence turns cannot be located in the product store are counted and reported, and recall is given with and without them.

## Other

**Plan and record.** This plan is committed on its own before its code is written. Person-days are listed on their own in plan v0, Section 6.

**Code version and deviations.** Runs set `AIJADE_GIT_COMMIT`; deviations are listed with date and reason. Fixed at commit (5 November 2026), each a reading of the text above made before the code:
- *The stages, in the order of the code.* (1) stored: the turn is in the product store; (2) candidate pool: on the text path the turns matching any query the client actually sent, by the server's own `ILIKE` predicate and with no limit; on the embedding path the caller's newest 2,000 items; (3) above the threshold: the embedding path's `MinSimilarity` of 0.3 after the verbatim bonus (equal to the pool on the text path); (4) the server's responses, the union over the client's calls, each limited to six items; (5) after the client drops the echo; (6) the prompt. Ranking loses nothing by itself: it decides what the limit of step 4 keeps, so it has no stage of its own.
- *How the stages are observed without touching the frozen files.* The client's calls and the server's responses are read at the HTTP handler. Steps 2 and 3 are recomputed by the harness with the same predicate and formula, and the harness checks on every question that its recomputation yields the response the server gave and that the five items it expects appear in the captured prompt; the numbers of mismatches are reported.
- *The questions are not written to the store.* The chat page records each utterance in the background, which would add every question to later questions' stores, so that write is left out and the store stays that of the conversation. The echo step is therefore expected to drop nothing, and is reported as measured.
- *The write path is the synchronous one.* The perceptions go through `POST /api/v1/v9/perception` on a server in the API role, with one store per conversation; a durable-queue deployment runs the same `ProcessPerceptionAsync` from its worker.
- *The stand-in endpoint is an HTTP handler in the harness's process*, not a separate server: it answers the client's chat completion and passes every other request to the real server.
- *The history is empty on every question*, so that one question's reply is not in the next prompt; the system message holding the memories does not depend on it.
