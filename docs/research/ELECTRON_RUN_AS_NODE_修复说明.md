# ELECTRON_RUN_AS_NODE 导致桌宠（electron-vite）启动失败 — 修复说明

> 关联：`start-pet.bat`（双击启动 `@proj-aijade/stage-tamagotchi` 桌宠模式）
> 日期：2026-07-30

## 现象

双击 `E:\AIJADE\start-pet.bat` 后窗口闪退；在终端直接跑
`pnpm --filter @proj-aijade/stage-tamagotchi dev` 报：

```
file:///.../out/main/index.js:9
import { BrowserWindow, Menu, Tray, app, ... } from "electron";
         ^^^^^^^^^^^^^
SyntaxError: The requested module 'electron' does not provide an export named 'BrowserWindow'
    at ... node:internal/modules/esm/module_job
Node.js v24.14.1
```

## 根因（关键）

**环境变量 `ELECTRON_RUN_AS_NODE=1` 被注入到了运行环境里。**

- 该变量一旦为 `1`，Electron 二进制会以「纯 Node 模式」启动，而不是浏览器进程模式。
- 纯 Node 模式下：
  - `process.type === undefined`（正常应为 `'browser'`）
  - `require('electron')` 返回的是 **npm 启动器包的路径字符串**（来自 `node_modules/electron/index.js` 的 `module.exports = getElectronPath()`），**而不是 Electron 内置模块**。
  - 因此主进程里 `import { BrowserWindow } from 'electron'` 这个具名 ESM 导入找不到 `BrowserWindow`，直接抛 SyntaxError。

### 验证（决定性证据）

```bat
REM 有 ELECTRON_RUN_AS_NODE=1（当前环境）：
electron _probe.cjs  ->  process.type=undefined ; require(electron).BrowserWindow=undefined

REM 彻底取消该变量后（env -u 或 PowerShell $null，注意：cmd 的 set VAR= 置空不够！）：
env -u ELECTRON_RUN_AS_NODE electron _probe.cjs  ->  process.type=browser ; require(electron).BrowserWindow=function ; app=object
```

`ELECTRON_RUN_AS_NODE` 不在 Windows 的 User/Machine 注册表里（不是持久环境变量），
而是被终端/沙箱环境注入的。它不在 `~/.bashrc` 等 rc 文件里，属于运行期注入，
所以无法在 rc 里简单去掉——但可以在 bat 内通过 PowerShell `$null` 真正移除后再启动。

## 为什么之前排查的方向都是死路

- ❌ 升级 electron-vite 5 → 6（beta）：运行时解析 `electron` 是 Electron 自己的事，与 electron-vite 版本无关。
- ❌ `.npmrc` 加 `node-linker=hoisted`：只影响依赖链接方式，无法让 `require('electron')` 返回内置模块。
- ❌ 给 `node_modules/electron/index.js` 打补丁：补丁内再 `require('electron')` 会循环解析回自身字符串，无效。
- ✅ 真正的开关是 `ELECTRON_RUN_AS_NODE`：清空后 Electron 正常以浏览器进程启动，内置 `electron` 模块立即可用。

## 修复

> ⚠️ **关键纠正**：不能简单地 `set "ELECTRON_RUN_AS_NODE="`（置空）。Electron 的 C++ 用
> `getenv("ELECTRON_RUN_AS_NODE")` 判断，**空字符串 `getenv` 仍返回非空指针**，会被当作"已设置"，
> 依然退化成纯 Node 模式、照样报错。必须**真正把变量从环境块移除**（`env -u` 或 PowerShell `$null`）。
> `cmd` 的 `set VAR=` 只能置空、无法删除继承变量，所以这里改用 **PowerShell 置 `$null` 后再启动**。

在 `start-pet.bat` 中，启动桌宠的命令改为（写在 `setlocal ... endlocal` 块内，不污染全局）：

```bat
set "NODE_OPTIONS="

REM 关键修复：若该变量被外部置为 1，Electron 会退化成纯 Node 模式启动，
REM require('electron') 只返回启动器路径字符串（而非内置模块），
REM 主进程 import { BrowserWindow } from 'electron' 会报
REM "does not provide an export named 'BrowserWindow'"。
REM cmd 无法真正删除继承变量，故用 PowerShell 把该变量置 $null（从环境块移除）后再启动。
powershell -NoProfile -ExecutionPolicy Bypass -Command "$env:ELECTRON_RUN_AS_NODE=$null; pnpm.cmd --filter @proj-aijade/stage-tamagotchi dev"
```

说明：必须显式写 `pnpm.cmd`，否则 PowerShell 会解析成 `pnpm.ps1` 触发 `PSSecurityException` 执行策略错误。
`$env:ELECTRON_RUN_AS_NODE=$null` 让该变量从 PowerShell 子进程的环境块中消失，后续
`pnpm → electron-vite → electron` 都继承不到它，Electron 即以正常的浏览器进程模式启动。

## 验证结果

清空后在 `E:\AIJADE` 运行 `pnpm --filter @proj-aijade/stage-tamagotchi dev`：
- `SyntaxError` 不再出现；
- 日志出现 `starting electron app...` 后主进程正常初始化
  （injeca 依赖注入 `windows:main` / `windows:chat` / `app:tray` 等 provider 就绪，WebSocket 连接建立）；
- 任务管理器中出现多个 `electron.exe` 进程（主进程 + 工具/Worker 子进程），桌宠已正常拉起。

## 备注

- 若你自己的终端/环境里也常带着 `ELECTRON_RUN_AS_NODE=1`（例如某安装器或终端配置设置的），
  建议在源头移除；`start-pet.bat` 里的清空是稳妥的局部兜底，不影响其他功能
  （`pnpm` / `vite` 都不依赖该变量）。
- 排查用的临时文件（`_pet_diag*.log`、`_esm_test.mjs`、`_cjs_test.cjs`、`_probe*.cjs`、临时 `C:\tmp\electest`）已全部清理。
