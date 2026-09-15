# THIRD-PARTY-NOTICES — 第三方代码、资产与模型

**文件版本**：v1.0
**最后更新**：2026-09-15
**适用范围**：本仓库**在库（in-tree）**分发的第三方内容，以及运行时会拉取的第三方模型。

> 本文件只登记**需要署名或需要遵守额外条款**的第三方内容。
> 完整依赖树见 `pnpm-lock.yaml`；其许可证清单可用 §5 的命令再生成。
> 项目自身与上游 Project AIRI 的衍生关系见 [`PROVENANCE.md`](./PROVENANCE.md)。

---

## 1. 上游代码基（首要第三方来源）

| 项 | 内容 |
|---|---|
| 项目 | Project AIRI |
| 仓库 | `https://github.com/moeru-ai/airi` |
| 许可证 | MIT |
| 版权 | `Copyright (c) 2024-PRESENT Neko Ayaka` |
| 使用方式 | 本仓库为其衍生作品；平台层代码继承自此 |

MIT 正文与版权行已逐字保留于根目录 [`LICENSE`](./LICENSE)。

---

## 2. 在库分发的第三方资产

### 2.1 字体（SIL Open Font License 1.1）

SIL OFL 要求：保留版权声明与许可证；**不得单独售卖字体**；含保留字体名（RFN）者，修改版不得沿用原名。

| 包 | 字体 | 版权 / 声明 | 许可证 | 文件 |
|---|---|---|---|---|
| `packages/font-chillroundm` | ChillRoundM（寒蝉圆体） | © 2023 ChillType；RFN：`ChillRoundF` `ChillRoundM` | SIL OFL 1.1 | `LICENSE` ✅ |
| `packages/font-cjkfonts-allseto` | cjkFonts 全瀨體 | © 2020 cjkFonts.io；RFN：`cjkFonts 全瀨體` `全瀨體` | SIL OFL | `license.txt` ✅ |
| `packages/font-departure-mono` | Departure Mono | © 2022–2024 Helena Zhang | SIL OFL 1.1 | `LICENSE` ✅ |
| `packages/font-xiaolai` | 小赖字体 | 〔见 §4 待核实项 1〕 | `package.json` 声明 SIL OFL | ⚠️ 包内**无**许可证文件 |

> 使用字体包的网页/桌面构建产物，必须随分发保留上述声明。
> 若将字体嵌入 APK / 安装包对外分发，OFL 的"不得单独售卖字体"约束仍然适用。

### 2.2 第三方渲染 / 运行时库（在库重新分发）

| 包 | 说明 | 许可证 |
|---|---|---|
| `packages/ccc` | 第三方组件包（AIJADE 侧整理） | MIT（`packages/ccc/LICENSE`） |
| `packages/stage-ui-spine` | Spine 运行时绑定：**双许可** | 本包自研代码 MIT；第三方运行时代码见 `packages/stage-ui-spine/LICENSE.md` |

> ⚠️ Spine 运行时（Esoteric Software）有**独立的商业授权条款**，与 OSI 许可证不同。
> 详见 `packages/stage-ui-spine/LICENSE.md`。任何对外分发前必须确认 Spine 授权范围。

---

## 3. 运行时会拉取、不在库分发的第三方模型与权重

这些内容**不入库**，但属于研究实验的可复现依赖，必须在论文的 "Materials / Implementation Details" 中声明。

| 模型 / 资产 | 用途 | 获取方式 | 需声明 |
|---|---|---|---|
| `qwen2.5-coder:7b-instruct`（Ollama 分发） | RQ-C 实验的候选生成器与自评估器 | `ollama pull qwen2.5-coder:7b-instruct` | 模型名、参数量、量化版本、分发渠道、**拉取日期** |
| `see-s-through` 系列权重（`.onnx` / `.pth` / `.safetensors`） | 图像分割 / 推理辅助 | 运行时下载（`.gitignore` 已排除） | 上游仓库与许可证 |
| `talking-head-anime-4-demo` 数据 | 头像动画 | 运行时下载（`.gitignore` 已排除） | 上游仓库与许可证 |
| TTS / ASR / 声纹模型 | 语音管线 | 见 `packages/audio*`、`packages/model-*` | 逐项登记 |

> 📌 **对 RQ-C 论文的直接影响**：实验结论依附于**特定模型的具体权重快照**。
> `temperature: 0` 只保证同一权重下的解码确定性，**不保证**跨模型版本可比。
> 因此论文必须写明模型标识与拉取时间；换用其他模型（或同一模型的更新版本）后结果可能不同，
> 这一点须在"效度威胁（Threats to Validity）"中显式声明。

---

## 4. 待核实事项

| # | 事项 | 风险 | 建议动作 |
|---|---|---|---|
| 1 | `packages/font-xiaolai` 包内**无许可证文件**，仅在 `package.json` 声明 "SIL Open Font License" | OFL 要求分发时随附许可证全文；仅有 package.json 声明在严格审查下不满足 | 从字体上游补入 OFL 1.1 全文与版权行，落到 `packages/font-xiaolai/LICENSE` |
| 2 | `packages/font-*` 与 `packages/ccc` 等包是否源自上游 AIRI，还是 AIJADE 新增 | 影响 §2 与 `PROVENANCE.md` §3 的贡献边界 | 与上游比对后归类 |
| 3 | `bucket/` 目录的来源与内容性质 | 若含第三方数据集/权重，需登记；若含用户数据，则不得入库 | 明确用途后登记或移出仓库 |
| 4 | `patches/` 下 8 个 `pnpm` 补丁的授权基础 | 对第三方包打补丁再分发，仍受原包许可证约束 | 逐项确认原包许可证允许修改分发 |
| 5 | 角色形象 / 立绘 / 语音样本的授权 | 与代码许可**无关**，常被审稿人与法务分别追问 | 单独建立资产授权台账 |

---

## 5. 再生成依赖许可证清单

```bash
# 方式一：pnpm 原生（需在无沙箱限制的终端执行，pnpm 需要写临时文件）
pnpm licenses list                 # 人类可读
pnpm licenses list --json          # 机器可读，便于汇总

# 方式二：仅筛出需要复核的非宽松许可证
pnpm licenses list --json \
  | jq -r 'to_entries[] | select(.key|test("GPL|AGPL|SSPL|CC-BY-NC|CC-BY-ND|UNLICENSED";"i")) | .key'
```

> ⚠️ 本仓库启用了 `enableGlobalVirtualStore`（见 `pnpm-workspace.yaml`），
> 依赖实体位于全局虚拟存储中并通过符号链接挂载。
> 直接遍历 `node_modules/.pnpm` 的脚本会因链接布局而漏读，**请优先使用 `pnpm licenses`**。

---

## 6. 维护约定

1. 新增在库分发的第三方资产（字体、图标、模型、示例数据、代码片段）→ **必须**同步登记到 §2。
2. 新增运行时会拉取的模型 / 数据集 → 登记到 §3，并在论文中声明。
3. 每季度或在每次投稿前复核一次 §4 待核实项。
4. 本文件与 `PROVENANCE.md` 分工：本文件管**第三方**，`PROVENANCE.md` 管**与上游的衍生关系与原创边界**。
