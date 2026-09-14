# 实时管线集成（记忆 + 结构化表现力）

本目录下的 `memory-performance.ts` 把 **分层记忆引擎**与 **结构化表现力导演**桥接进
AIJADE 的对话运行时（`createChatOrchestratorRuntime`），不修改 orchestrator 内部实现，
完全借由它已有的扩展点（`runtimeContextProviders` / 生命周期回调 / token 钩子）。

## 两条管线

### 1. 记忆管线（`createMemoryBridge`）
- **召回注入**：每次发送前 `prepareSend(userText)` 预计算一次 `port.recall(userText)`，
  结果以 `runtimeContextProvider` 的形式（FIFO 缓冲）注入提示，上下文 id 为
  `memory:recall`，策略 `ContextUpdateStrategy.ReplaceSelf`（扁平 bullet，避免弱模型
  把 XML 包装原样回灌）。无相关记忆时返回 `null`，调用方跳过注入。
- **回合持久化**：`onUserMessageAppended` / `onAssistantMessageAppended` 把每条消息写进
  情景层（episodic tier）；`onAssistantTurnReady` 触发 `maybeCompact()`（达到阈值时
  压缩 + 蒸馏长期事实）。
- 底层引擎来自 `@proj-aijade/memory-pgvector`（`LayeredMemory` + `MemoryPort`），默认用
  无依赖的哈希 embedder + 内存向量库；生产可换 pgvector 存储与真实 embedder。

### 2. 表现力管线（`createPerformanceBridge`）
- `onMessageSendStarted` → `director.enterListen()`（用户说话，进入 listen 态）。
- `onTokenLiteral` → `director.onToken()`：**首个流式 token 即进入 speak 态**，消除
  “先沉默后出声”的人工智障感。
- `onTokenSpecial` → `director.applyMarkers()`（消费 `<|emotion>|<|gesture>|...` 标记）。
- `onStreamEnd` → `director.onTurnEnd()`（落入 alive-idle 的 silence 态）。
- 每次状态/线索变化都通过 `onState(state)` 推给 UI（即 `performanceState`），驱动 VRM
  表情 / 口型 / 视线等实时表现。三态机（listen / speak / silence）+ 情绪 / 手势 / 视线 /
  音乐 / 关系增量，直接对应 LPM 1.0 的实时状态与多模态控制。

## 接线位置（`stores/chat.ts`）
```ts
const memoryPort = createLayeredMemoryPort(createDefaultLayeredMemory(), { scope: 'chat' })
const memoryBridge = createMemoryBridge(memoryPort)
const performanceDirector = createPerformanceDirector()
const performanceState = ref<PerformanceState>(performanceDirector.snapshot())
const performanceBridge = createPerformanceBridge(performanceDirector, (s) => {
  performanceState.value = s
})

const runtime = createChatOrchestratorRuntime(
  capabilities.wrapDeps(
    performanceBridge.wrapDeps(
      memoryBridge.wrapDeps(baseDeps)
    )
  ), // 三层桥接嵌套
)
performanceBridge.registerHooks(runtime) // token 钩子注册
capabilities.registerHooks(runtime)

async function ingest(sendingMessage, options, targetSessionId?) {
  await memoryBridge.prepareSend(sendingMessage) // 发送前预计算召回
  return runtime.ingest(sendingMessage, options, targetSessionId)
}
```

## 参考映射
- **AkaneCompanionLab / Hermes Scope-Recall / “活人感”长期记忆** → 分层记忆引擎
  （`@proj-aijade/memory-pgvector`）。
- **LPM 1.0（arXiv:2604.07823）** → 三态实时状态（listen / speak / silence）+ 多模态表现标记。
- **StreamPet / “告别人工智障式沉默”（BV1yT96mE6t）** → speak 态在首个流式 token 进入，
   closure 沉默间隙。

## 测试
`memory-performance.test.ts` 用轻量 mock（不加载重型引擎）覆盖两条桥：
- 记忆桥：recall FIFO 注入（含空查询跳过）、回合持久化、回调链式不覆盖。
- 表现力桥：发送开始 → listen、token 流驱动 director、流结束 → silence、状态推送 UI。

运行（指定文件，避免触发需要浏览器环境的 `.browser.test.ts`）：
```bash
pnpm --filter @proj-aijade/stage-ui run test:run src/stores/chat/memory-performance.test.ts
```
