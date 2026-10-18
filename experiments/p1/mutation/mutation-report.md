# J1 mutation experiment (.NET implementation)

- baseline: 287/287 assertions green

| ID | file | expected capture | predicted | observed | new red | false red |
|---|---|---|---|---|---|---|
| FU-01 | `src/Aijade.Memory/Kernel/Events.cs` | kernel | caught | caught | 1 | 0 |
| FU-02 | `src/Aijade.Memory/Kernel/Events.cs` | kernel | caught | caught | 1 | 0 |
| FU-03 | `src/Aijade.Server/V9/Boundary.cs` | http | caught | caught | 2 | 0 |
| FU-04 | `src/Aijade.Server/V9/V9Endpoints.cs` | http | caught | caught | 97 | 51 |
| FU-05 | `src/Aijade.Server/V9/Boundary.cs` | http+no-write | caught | caught | 2 | 0 |
| FU-06 | `src/Aijade.Memory/Kernel/Events.cs` | guard+kernel | caught | caught | 21 | 19 |
| FU-07a | `src/Aijade.Server/V9/V9EventService.cs` | http+no-write | caught | survived | 0 | 0 |
| FU-07b | `src/Aijade.Server/V9/V9EventService.cs` | http+no-write | caught | caught | 3 | 0 |
| FU-08 | `src/Aijade.Server/V9/V9EventService.cs` | http | survived | survived | 0 | 0 |
| FU-09 | `src/Aijade.Server/V9/V9EventService.cs` | no-write | caught | caught | 2 | 0 |
| FU-10 | `src/Aijade.Server/V9/V9EventService.cs` | none | survived | survived | 0 | 0 |
| FU-11 | `src/Aijade.Server/V9/V9EventService.cs` | none | survived | survived | 0 | 0 |
| FU-12 | `src/Aijade.Server/V9/ServerRuntime.cs` | none | survived | survived | 0 | 0 |
| FU-13 | `src/Aijade.Server/V9/V9Endpoints.cs` | none | survived | survived | 0 | 0 |
| FU-14 | `src/Aijade.Server/V9/V9EventService.cs` | http+no-write | caught | caught | 11 | 11 |
| FU-15 | `src/Aijade.Server/V9/V9EventService.cs` | none | survived | survived | 0 | 0 |
| FU-16 | `src/Aijade.Memory/BioticMemory.cs` | none | notImplemented | notImplemented | - | - |
| FU-17 | `src/Aijade.Server/V9/Boundary.cs` | none | survived | survived | 0 | 0 |
| FU-18 | `src/Aijade.Memory/Kernel/Events.cs` | none | survived | survived | 0 | 0 |
| FU-19 | `src/Aijade.Memory/Kernel/Events.cs` | none | notImplemented | notImplemented | - | - |

caught 9, survived 9, notImplemented 2, mutationError 0; **diffScore = caught / (caught + survived) = 0.5**
