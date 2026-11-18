# Live2D chat and mask engineering evidence

The product renderer in this record is the AIJADE Web companion stage on Mac. The research comparison in dissertation Section 7.3 uses its separately specified Godot renderer and prospective acceptance procedure.

## Retained face-mask repair comparison

The original model uses 49 distinct drawable mask groups across 181 clipped drawables. The previous single packed buffer supports 36 groups. The first repair enabled Cubism's per-drawable masks when the group count exceeded that capacity. The matched neutral-face crop yielded 281 strongly red pixels out of 1,232 before the repair and 12 afterward. The repaired path retained the intentional blush and its reset. The report records the fixed pixel rule, window lengths, frame totals and hashes of the underlying browser observations. [Historical mask repair results](historical-mask-repair.json)

## Paired mask comparison

Two paired Mac Chromium runs reversed the execution order between the per-drawable reference and the two-buffer candidate. Both modes yielded 12 strongly red pixels in the 1,232-pixel neutral face region. Across each matched neutral frame, zero pixels had a channel difference of 16 or more and the maximum channel difference was 4. The checks also exercised intentional blush, concern, expression reset, mouth movement and gaze. With the same candidate adapter and the packed-mask setting absent, the stage used per-drawable high-precision masks. [Paired mask results](packed-mask-comparison.json)

| Per-run measurement | Per-drawable reference | Two-buffer candidate |
| --- | --- | --- |
| Median mask clears per presented frame | 127, 127 | 2, 2 |
| Median WebGL draw calls per presented frame | 682, 682 | 556, 556 |
| Median JavaScript dispatch to presentation | 3.4 ms, 3.6 ms | 2.5 ms, 2.9 ms |
| Presented frames per second in approximately two-second samples | 20.50, 21.47 | 30.27, 30.27 |
| Calculated base-level mask texture storage | 0.25 MiB | 4.5 MiB |

Dispatch timing covers JavaScript work through presentation on the sampled host. Texture storage is calculated from the dimensions and number of RGBA mask targets.

## Browser chat and continuous rendering

The actual AIJADE chat page sent messages to its local server, which used deterministic streamed replies and served macOS-generated speech through its voice gateway. Chromium played the WAV responses through Web Audio and the tests inspected the native Cubism parameters. The observed states included intentional blush, tears and a neutral reset. The browser trace matches the WAV responses, applied-render receipts and completed assistant replies. One interrupted streaming reply per mode produced no new completed message or speech playback.

| Browser observation | Per-drawable reference | Two-buffer configuration |
| --- | --- | --- |
| Completed fixture exchanges with speech | 7 | 13 |
| Continuous observation window | 300.04 s | 900.02 s |
| Presented frames in window | 8,055 | 26,890 |
| Neutral face samples | 29 | 87 |
| Largest strongly red share of the fixed face crop | 2.03% | 2.32% |
| WebGL context losses | 0 | 0 |

The predeclared neutral failure threshold was 11% strongly red pixels in the sampled face region. The captured trace includes foreground stage samples at about ten-second intervals and returns to neutral after scheduled emotion-to-neutral reply pairs. An initial preflight captured a stale generated static-asset manifest and was excluded as recorded. The original recorder's event assertion omitted the public topic prefix. Independent readback verified the canonical `aijade.lpm.render_ready` topic, HTTP 201 responses and per-turn parameter hashes against the preserved reports. [Browser integration and readback](receipt.json)

## Conversational phrasing reference

The linked video informed a positive style instruction for Web and bridge replies. The instruction favors phrasing tied to the current context, variation in recurring openings and endings, and follow-up questions that help the conversation. User-requested formats, precise facts and tool outcomes retain their existing handling. The reference record describes the machine-transcript and comment reading scope. [Source and adoption record](conversational-reference.json) · [Video](https://www.bilibili.com/video/BV1gMsM6TE9u/)

A separate paired local-model check used eight fixed synthetic contexts and Qwen2.5-Coder 1.5B. Across the five style cases, a fixed pattern detector registered six hits with the prior instruction and four with the new instruction. Distinct opening clauses went from one to two, and replies ending in a question went from five to four. Arithmetic and exact quotation matched in both arms. The exact JSON example failed in both arms. A preceding Llama 3.1 8B cold start timed out before producing a reply. This probe measures the listed controls on the tested model and contexts. [Probe scope and aggregates](conversational-reference.json)

The renderer can load a locally licensed DeepSeek-chan model. Original art and separation are by 神宫凉子, and Live2D modeling is by 霓虹猫_NeonNeko. The public archive contains aggregate measurements and integrity hashes. Original character files, screenshots, recordings and private test data remain in the local archive.
