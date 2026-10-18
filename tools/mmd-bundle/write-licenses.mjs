// Ship the licence texts of everything bundled into mmd-backend.js next to it.
import { readFileSync, writeFileSync, rmSync } from 'node:fs';
const parts = [
  ['@babylonjs/core (Apache-2.0)', 'node_modules/@babylonjs/core/license.md'],
  ['babylon-mmd (MIT)', 'node_modules/babylon-mmd/LICENSE'],
  ['babylon-mmd WebAssembly runtime lib/index_bg.wasm (MIT; embeds the Bullet physics engine, zlib licence)', 'node_modules/babylon-mmd/esm/Runtime/Optimized/wasm/spr/LICENSE'],
];
const text = parts.map(([name, file]) => `===== ${name} =====\n\n${readFileSync(file, 'utf8')}`).join('\n\n');
writeFileSync('../../src/Aijade.UI/wwwroot/lib/THIRD-PARTY-LICENSES.txt', text);
try { rmSync('../../src/Aijade.UI/wwwroot/lib/mmd-backend.js.map'); } catch { /* not built */ }
