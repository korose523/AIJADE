# Fourth recorded deviation: the external renderer's behavior driver (21 November 2026)

Added on 23 November 2026 at the supervisor's request. Until this note, the repository held only the source hashes of this change, with no source and no diff.

## What changed and why

The sixth Mac qualification attempt stopped because one renderer frame stalled for about 40 seconds. The seven intents that arrived during the stall were consumed in one frame and recorded in one `RenderStatePacket`. Before the seventh attempt, the client's behavior driver was changed to consume one intent per rendered frame. Packets of a later trace now wait until the previous intent's `RenderStatePacket` has been written.

- The renderer is the native MMD client on the Godot engine from the author's separate project (MOSAIC). The same client is the external renderer of thesis Section 4.5.10 (P1 Section 5.10).
- The change touches one file, `clients/godot-scene/BehaviorDriver.cs`. The full unified diff is [`BehaviorDriver.cs.diff`](BehaviorDriver.cs.diff): one line replaced and 15 lines added, one of them a new queue field.
- The change was made only in the copy of the client prepared for this study (`prepared-renderer-v4`, kept in the author's local research directory). The client's own project was not changed.
  - Its working copy still holds `BehaviorDriver.cs` at revision 614, last changed at r614, with SHA-256 `7442e66a…`.
  - That is the same file as the "before" side below.

## Hashes

| Item | Before (attempts 1–6; Chapter 4) | After (attempt 7 and the 40-pair held-out comparison) |
|---|---|---|
| `clients/godot-scene/BehaviorDriver.cs` | `7442e66ad91d7d47c2b978a1fc655095b2005fbf809cb750349bfd5cfeca2ac0` | `456cc8f740f5cccae854f551370248ec1b27dad4ec4f6ab351bdcfeaeda8ce74` |
| Built `MosaicScene.dll` | `5e93bec4c58fadc6989d58bbdf3c254c6d0fb72d87e809b94a538c32f5761deb` | `12d4de44f2bcab39d7d47c34d65655291fb9f450af070100c18a9d926b1eb0ce` |
| Built `MosaicScene.pdb` | `a31ed44af0d01cb0ac0f559f9b64b3f805a6011eb46228bc6b87e1e857afac3d` | `011cb1d80c7ee9926056bb7afe294a77f878d6f7da5e895ddf6df6c338327c1c` |
| `MosaicScene.csproj`, `.deps.json`, `.runtimeconfig.json` | unchanged | unchanged |
| `aijade-prepared-renderer.json` (the copy's own record) | — | `96ab493dac927774700b5398bc684c99866f779f3d498022fa2ca1c2850a71cd` |

- **Where the hashes come from.** The "before" build hashes are those recorded in `attempts-20261121/attempt-06/launch.json`. The "after" build hashes are those in `attempt-07/launch.json`, `construction-freeze.json` and `qualification-acceptance.json`.
- **Other files.** Apart from `BehaviorDriver.cs` and the copy's own record, the source tree of the prepared copy is identical before and after. The comparison excluded build output.
- **Build.** The client was rebuilt offline. The build log names the output `clients/godot-scene/.godot/mono/temp/bin/Debug/MosaicScene.dll`, with 0 warnings and 0 errors.

## Correction of a sentence in the attempt-7 records

The `adjustment` field of the prepared copy's record was carried into the attempt-7 `launch.json`, `construction-freeze.json` and `qualification-acceptance.json`. It reads:

> Only refuse automatic rebuild in the explicit prebuilt mode; installed Godot/log sandbox are supplied separately. Client C# and renderer logic unchanged. 21 November 2026, fourth recorded deviation: BehaviorDriver consumes one intent per rendered frame; client rebuilt offline (Optimize=true).

- **The contradiction.** The sentence "Client C# and renderer logic unchanged" was written on 16 November for the first prepared copy, and it was true then. The 21 November text appended to it says the opposite.
- **Corrected wording.** "Only refuse automatic rebuild in the explicit prebuilt mode; installed Godot/log sandbox are supplied separately. From 21 November 2026 (fourth recorded deviation), one client C# file differs from the client's project: BehaviorDriver.cs consumes one intent per rendered frame (diff in renderer-change-20261121/); client rebuilt offline."
- **Why the records stay as written.** The three records are hash-bound. Each was published before the run that used it, and later records cite their SHA-256. They are therefore kept byte for byte, and this note is the correction. The SHA-256 values of the records as published:
  - `attempts-20261121/attempt-07/launch.json`: `00f64b60d472a2d67454fdacd4c02ed8856204cdba03600cdc6112b6dcccc952`
  - `construction-freeze.json`: `a3315b5bd96b438128447c1bc77e4d4f313adf50fa3056343888540136f5974f`
  - `qualification-acceptance.json`: `83979fad469a866ea712f475ff9e48077ef571e8579f0686afbd94d758c177c7`

## Does the change affect Chapter 4?

No. The Chapter 4 runs (6 November 2026, commit `6ca1618`) used the client at revision 614 of `BehaviorDriver.cs`, which is the "before" file. In those runs, as in attempts 1 to 6, one frame could consume several intents.

The archived Chapter 4 render-state files (`experiments/p1/external-renderer/r*/*/client*/aijade-render-state.jsonl` at the frozen research commit) were counted:

- 15 files with 135 `behavior_overlay_pre_solve` rows;
- in every row, each consumed packet carries a trace identifier;
- 0 rows consumed packets of more than one intent.

The Chapter 4 receipts therefore each stand for one intent. The thesis states this in Section 4.5.10, with the count rendered from those files by `docs/_工具/facts.py` (`p1.x.merged`, `p1.x.preRows`).
