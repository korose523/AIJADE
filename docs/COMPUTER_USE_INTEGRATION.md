# 真实电脑操控接入 Hermes 融合缝 — 交付说明

> 生成日期：2026-07-11
> 范围：AIJADE 电脑操控（computer-use）能力接入对话运行时，并在本机 Windows 真机验证闭环

## 交付目标（原始 4 项意图）

1. 真实电脑操控接 `hermes-bridge.ts` 融合缝
2. 把「AIJADE 桥模式扩展」沉成可复用 Skill
3. 检查全部 AIJADE 项目代码，优化融合接入与引用项目
4. 本地真机测试，修改 bug

## 已实现交付物

### A. Windows 真机执行器（win32-local）
- 新增 `services/computer-use-mcp/src/executors/win32-local.ts`
  - 通过 PowerShell + .NET（user32/GDI）实现 `DesktopExecutor` 全接口：
    `observeWindows` / `getDisplayInfo` / `takeScreenshot` / `click` / `typeText` / `pressKeys` / `scroll` / `openApp` / `focusApp`。
  - 每个脚本 `try/catch` 输出 `{ok,error,...}` JSON，脚本以 `Exit 0` 结束。
- 新增 `services/computer-use-mcp/src/utils/powershell.ts`
  - `runPowerShell` / `buildMinimalEnv` / `parsePowerShellJson`。
  - **解决 Windows 65535 字节环境变量块上限**：只转发最小白名单 env，避免继承 ~365KB 的 `process.env` 导致子进程 spawn 失败。

### B. 统一 `computer_use` 工具（融合缝缺失的一半）
- 新增 `services/computer-use-mcp/src/server/computer-use-unified.ts`
  - 把 Hermes 风格 `action`（capture/click/scroll/type/key/list_apps/focus_app 等）映射到 server 内部 `ActionInvocation`，复用既有 `executeAction` 引擎落到 `win32-local`。
- `register-tools.ts` 注册 `server.tool('computer_use', …)`，使 LLM 看到的 `computer_use`（`computer_use::computer_use`）在 server 端有真实落点。

### C. 接线与配置
- `types.ts`：`ExecutorKind` 增加 `'win32-local'`。
- `config.ts`：`parseExecutor` / `permissionChainHint` 支持 `win32-local`。
- `runtime.ts`：`createExecutor` 路由到 `createWin32LocalExecutor`。
- `formatters.ts`：修复 `platform` 用法（`node:process` 导出字符串而非函数）；`local-windowed` 描述。
- `apps/stage-tamagotchi/src/main/services/airi/mcp-servers/index.ts`：依据 `process.platform` 自动选 executor（`win32`→`win32-local`），并以精选最小 env 启动 `computer_use` MCP server。
- `packages/stage-ui/src/stores/chat.ts`：确认 `realComputerUseClient → createComputerUseMcpTransport → createHermesBackend → createComputerUseCapability → createAgentCapabilitiesBridge` 已串接，且 `bridge.wrapDeps` / `registerHooks` 确有调用（融合缝真正并入运行时）。
- **修复真实 bug**：`chat.ts` 后台能力 LLM 硬编码 `qwen2.5:7b`，但本机 Ollama 仅装 `qwythos-9b:Q8_0` → 所有后台自动建技能/持续学习 LLM 调用静默失败。已改为 `qwythos-9b:Q8_0`。

### D. 可复用 Skill
- `~/.workbuddy/skills/airi-bridge-extension/`（`SKILL.md` + `references/contracts.md`），已校验打包（前序会话完成）。

## 真机验证结果（本机 Windows）

| 验证项 | 方式 | 结果 |
|--------|------|------|
| granular 路径 | `mcp_smoke2.mjs` 直调 `desktop_*` | 枚举 10 真实窗口、捕获 4480×1080 双屏截图 ✅ |
| 统一工具注册 | `mcp_smoke_unified.mjs` | 工具数 71→72，含 `computer_use` ✅ |
| 统一工具真机执行 | `computer_use(list_apps)` / `capture` | 8 真实窗口 / 真实截图；`drag` 优雅 `unsupported` ✅ |
| **完整 LLM 驱动 e2e** | `e2e_llm_drive.mts`（忠实复刻 Electron 接线，绕开 GUI 窗口） | 真实 Ollama `qwythos-9b` 自主调用 `computer_use`，枚举 8 窗口并基于真实数据回答 → `LLM_DRIVEN_DESKTOP_OK` ✅ |
| 后台 skill-forge 真机 | `createSkillForge.detectTeachableMoment` | 真实模型返回结构化草案 → `SKILL_FORGE_OK` ✅ |
| 类型检查 | 5 个融合包 typecheck | 全绿 ✅ |
| 单元测试 | `computer-use-mcp` vitest | 646 passed / 5 failed（5 个为既有 Windows 环境失败：`/tmp` POSIX 假设、`spawn /bin/zsh ENOENT`，与本次改动无关，无回归）✅ |

## 已知限制
- 完整 e2e 以「忠实无头 harness」形式验证（复用与 Electron 完全相同的编排接线，仅跳过渲染窗口），未启动 GUI 窗口本身——本环境无法向 GUI 窗口键入，但编排逻辑与工具调用路径与 Electron 一致。
- 5 个 pre-existing 测试失败为 Windows 环境本身问题，非本次引入。

## 关键文件清单
- `services/computer-use-mcp/src/executors/win32-local.ts`（新增）
- `services/computer-use-mcp/src/utils/powershell.ts`（新增）
- `services/computer-use-mcp/src/server/computer-use-unified.ts`（新增）
- `services/computer-use-mcp/src/{types,config,runtime}.ts`、`server/{register-tools,formatters}.ts`（修改）
- `apps/stage-tamagotchi/src/main/services/airi/mcp-servers/index.ts`（修改）
- `packages/stage-ui/src/stores/chat.ts`（修改：后台模型修复）
- `packages/stage-ui/e2e_llm_drive.mts`（新增：可重跑的真机 e2e 脚本）
