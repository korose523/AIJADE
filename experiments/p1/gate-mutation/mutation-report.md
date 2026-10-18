# P1 gate-mutation experiment (.NET implementation)

- baseline: 16/16 assertions green

| ID | file | expected capture | predicted | observed | new red | false red |
|---|---|---|---|---|---|---|
| P1 | `src/Aijade.Server/V9/PromotionService.cs` | tamper matrix | caught | caught | 3 | 0 |
| P2 | `src/Aijade.Server/V9/PromotionService.cs` | tamper matrix | caught | caught | 1 | 0 |
| P3 | `src/Aijade.Server/V9/PromotionService.cs` | tamper matrix | caught | caught | 5 | 0 |
| P4 | `src/Aijade.Server/V9/PromotionService.cs` | tamper matrix | caught | caught | 2 | 0 |
| P5 | `src/Aijade.Server/V9/PromotionService.cs` | tamper matrix | caught | caught | 2 | 0 |
| A1 | `src/Aijade.Memory/V9/ShadowParams.cs` | tamper matrix | caught | caught | 3 | 0 |
| A2 | `src/Aijade.Memory/V9/ShadowParams.cs` | tamper matrix | caught | caught | 5 | 0 |
| E1 | `src/Aijade.Memory/Development/Vse.cs` | tamper matrix | caught | caught | 1 | 0 |
| E2 | `src/Aijade.Memory/Development/Vse.cs` | tamper matrix | caught | caught | 1 | 0 |
| E3 | `src/Aijade.Memory/Development/Vse.cs` | tamper matrix | caught | survived | 0 | 0 |
| E4 | `src/Aijade.Memory/Development/Vse.cs` | tamper matrix | caught | caught | 1 | 0 |
| E5 | `src/Aijade.Memory/Development/Vse.cs` | tamper matrix | caught | caught | 1 | 0 |
| E6 | `src/Aijade.Memory/Development/Vse.cs` | tamper matrix | caught | caught | 1 | 0 |
| G1 | `src/Aijade.Memory/Pgc/PgcGate.cs` | tamper matrix | caught | survived | 0 | 0 |
| G2 | `src/Aijade.Memory/Pgc/PgcGate.cs` | tamper matrix | caught | survived | 0 | 0 |
| G3 | `src/Aijade.Memory/Pgc/PgcGate.cs` | tamper matrix | caught | survived | 0 | 0 |
| G4 | `src/Aijade.Memory/Pgc/PgcGate.cs` | tamper matrix | caught | survived | 0 | 0 |
| G5 | `src/Aijade.Memory/Pgc/PgcGate.cs` | tamper matrix | caught | caught | 2 | 0 |
| G6 | `src/Aijade.Memory/Pgc/PgcGate.cs` | tamper matrix | caught | survived | 0 | 0 |
| G7 | `src/Aijade.Memory/Pgc/PgcGate.cs` | tamper matrix | caught | survived | 0 | 0 |

caught 13, survived 7, notImplemented 0, mutationError 0; **diffScore = caught / (caught + survived) = 0.65**
