# Third-party notices

Every third-party component must be listed here with its licence before it is merged. Only permissive licences
(MIT, Apache-2.0, BSD) are accepted (docs/STATUS.md §1).

| Component | Used for | Licence |
|---|---|---|
| .NET runtime and SDK | platform | MIT |
| xunit.v3, xunit.runner.visualstudio | tests | Apache-2.0 |
| Microsoft.NET.Test.Sdk | tests | MIT |
| Jint 4.16.3 | JavaScript sandbox of the skill benchmark (Aijade.Research) | BSD-2-Clause |
| Acornima 1.7.0 (dependency of Jint) | JavaScript parser | BSD-3-Clause |
| Npgsql 10.0.3 | PostgreSQL access of the server, P1 driver and mutation runner | PostgreSQL License (OSI-approved, BSD/MIT-style permissive) |
| StackExchange.Redis 3.3.1 (+ Pipelines.Sockets.Unofficial) | job queues between the API and worker processes | MIT |
| Microsoft.AspNetCore.Authentication.OpenIdConnect 10.0.12 (+ Microsoft.IdentityModel.*) | OIDC sign-in | MIT |
| Babylon.js (@babylonjs/core) 9.28.0, bundled into `src/Aijade.UI/wwwroot/lib/mmd-backend.js` | MMD stage rendering | Apache-2.0 (text shipped in `lib/THIRD-PARTY-LICENSES.txt`) |
| babylon-mmd 1.3.0, bundled likewise | PMX/PMD/VMD loading and MMD runtime | MIT |
| babylon-mmd WebAssembly runtime (`src/Aijade.UI/wwwroot/lib/index_bg.wasm`, single-threaded release build), which embeds the Bullet physics engine | MMD hair and cloth physics | MIT (babylon-mmd); Bullet: zlib licence |
| esbuild 0.28.2 (build tool only, not shipped) | bundling the MMD backend | MIT |
| Microsoft.AspNetCore.Components.Web / WebAssembly (+ DevServer, Server) 10.0.12 | web client | MIT |
| Microsoft.AspNetCore.Mvc.Testing 10.0.12 (+ Microsoft.AspNetCore.TestHost) | in-process server tests | MIT |
| Xiaolai font v3.126 (LXGW, based on Seto Font by Nozomi Seto), `src/Aijade.UI/wwwroot/fonts/xiaolai/Xiaolai-Regular.ttf`, SHA-256 `e2f68daf…802da2` | CJK interface text | SIL Open Font License 1.1 (text shipped beside the font as `OFL.txt`) |
| Microsoft.Extensions.AI.Abstractions 10.10.0 | interoperability with the .NET AI client ecosystem | MIT |
| Discord.Net 3.20.1 | Discord connector | MIT |
| Telegram.Bot 22.10.3.1 | Telegram connector | MIT |
| ModelContextProtocol / ModelContextProtocol.AspNetCore 2.2.0 | MCP server (/mcp), MCP client (tool hub), computer-use MCP server | Apache-2.0 |
| Microsoft.Extensions.Hosting 10.0.12 | bots and computer-use hosts | MIT |
| Microsoft.Playwright 1.63.0 (test only, not shipped; bundles the Playwright Node driver and downloads Chromium on first use) | browser end-to-end tests | MIT (Chromium: BSD-3-Clause and others, per its own notices) |

## Data used but not redistributed

| Dataset | Used for | Licence | How to obtain |
|---|---|---|---|
| LoCoMo (Maharana et al., ACL 2024), `locomo10.json`, SHA-256 `79fa87e9…98ff4` | memory retrieval evaluation (P4) | see the dataset's own terms | download separately; point `AIJADE_LOCOMO` at it |
