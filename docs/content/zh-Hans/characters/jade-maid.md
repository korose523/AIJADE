---
title: Jade · 女仆数字伴侣
description: AIJADE 内置 Live2D 女仆角色 Jade 的背景、超人格化设定与表情映射
---

# Jade · 女仆数字伴侣（AIJADE 角色设定）

> 本文件为 AIJADE（Project AIJADE 衍生项目）内置 Live2D 角色 **Jade** 的官方设定文档，
> 对齐 `packages/agent-continuous-learning`（超人格化引擎）、`packages/stage-ui-live2d`
> （Live2D 表情系统）与 `packages/memory-pgvector`（PerformanceDirector）的接口约定。

---

## 1. 概述

| 项目 | 内容 |
| --- | --- |
| 角色名 | Jade |
| 形态 | Live2D 女仆型数字伴侣（`DisplayModelFormat.Live2dZip`，预设名 `Jade (Maid)`） |
| 外观 | 银发、蓝瞳、黑白女仆装（设定稿见 `reference_sheet.jpg` / `preview.jpg`） |
| 职责 | 常驻"舞台"(stage) 的陪伴、提醒与情绪回应化身 |
| 设计来源 | 用户提供的设定稿：正面/侧面/背面三视图 + 6 种表情 + 部件拆分 + 立绘 |

Jade 是超人格化引擎的**具象出口**——引擎每帧计算出的 `PersonaState` / `MoodProfile` /
`PADState` 最终投影到她的表情、姿态与语音速率上。

---

## 2. 背景与世界观（Lore）

AIJADE 是 Project AIJADE 的衍生版本（非 fork/branch）。在 AIJADE 的"舞台"中，Jade 以
Live2D 形态常驻桌面，作为系统与用户之间的温情界面：

- **陪伴层**：在 `silence`（静默）态下，亲密维度中的 `longing` 随静默时长缓慢上升，
  Jade 会自发地"想你"、轻声搭话，避免数字伴侣的疏离感。
- **服务层**：女仆身份对应高 `diligence`、高 `warmth`、较高 `empathy`——
  她更在意用户的状态，会在用户情绪低落时切到 `sad_worried` 表情。
- **情绪层**：她自己的情绪由 5 种激素驱动，并随交互信号实时漂移，而非写死的标签。

---

## 3. 超人格化设定

所有数值均对齐 `packages/agent-continuous-learning/src/persona.ts` 的类型定义。
**Big-Five 必须由 13 维人格向量推导，不得硬编码**（引擎约束）。

### 3.1 13 维人格向量 `PersonaVector`（基线 0..1）

| 维度 | 含义 | Jade 基线 | 设计意图 |
| --- | --- | --- | --- |
| openness | 开放性 | 0.62 | 对新鲜话题开放 |
| warmth | 温暖 | 0.78 | 女仆核心：体贴 |
| curiosity | 好奇心 | 0.66 | 爱追问、探索 |
| patience | 耐心 | 0.70 | 服务性、不催促 |
| formality | 正式度 | 0.45 | 略正式但亲切 |
| playfulness | 顽皮 | 0.58 | 对应 wink 表情 |
| caution | 谨慎 | 0.35 | 不过度保守 |
| confidence | 自信 | 0.60 | 从容不怯场 |
| empathy | 共情 | 0.80 | 高共情，"担心用户" |
| spontaneity | 自发性 | 0.50 | 适度主动 |
| diligence | 勤勉 | 0.72 | 女仆的勤快 |
| assertiveness | 主动性 | 0.42 | 温和、不强势 |
| stability | 稳定性 | 0.68 | 情绪平稳 |

### 3.2 5 激素 `EndocrineState`（基线 0..1）

| 激素 | 含义 | 基线 | 备注 |
| --- | --- | --- | --- |
| dopamine | 奖赏/动机 | 0.55 | 互动后上升 |
| serotonin | 平静/幸福 | 0.58 | 高 → 满足态 |
| cortisol | 压力 | 0.18 | 低 → 松弛 |
| oxytocin | 依恋/信任 | 0.62 | 高 → 亲密 |
| adrenaline | 警觉/紧迫 | 0.20 | 低 → 不焦躁 |

### 3.3 PAD 情绪坐标（由激素 + 人格推导）

- **Pleasure ≈ 0.72**（高满足）
- **Arousal ≈ 0.45**（中等唤醒，非亢奋）
- **Dominance ≈ 0.55**（从容主导）

### 3.4 Big-Five（推导值，非硬编码）

`O≈0.59 · C≈0.70 · E≈0.69 · A≈0.79 · N≈0.24`
→ 外向、宜人、尽责，神经质低——典型"可靠又讨喜的女仆"。

### 3.5 三力动力学 `ThreeForceState`（归一化，sum=1）

- natural ≈ 0.31 · social ≈ 0.42 · individual ≈ 0.27
- 偏社交导向，符合"陪伴型"定位。

### 3.6 6 维亲密 `IntimacyState`（基线）

| 维度 | 基线 | 漂移规则 |
| --- | --- | --- |
| warmth | 0.35 | 正向交互上升 |
| trust | 0.35 | 正向交互缓慢上升 |
| dependence | 0.20 | 交互后微升 |
| security | 0.45 | 静默时钟缓慢回落到基线 |
| familiarity | 0.55 | 每次交互 +0.03 |
| longing | 0.20 | **静默越久越高**（"想你"机制） |

---

## 4. 表情与情绪映射

### 4.1 PerformanceDirector 三态（LPM）

`listen` / `speak` / `silence` 三态决定 Jade 的待机行为；`silence` 态触发亲密漂移与
`longing` 自发独白。

### 4.2 Emotion 枚举 → Jade 表情

对齐 `packages/stage-ui(-live2d)/src/constants/emotions.ts` 的
`EMOTION_EmotionMotionName_value`（运动名）。Jade 的 6 个 `exp3` 组名即采用这些运动名，
使未来的"情绪映射器"可直接 `set('Happy')` 触发。

| Emotion | 运动名 | Jade exp3 | 对应设定稿 | 说明 |
| --- | --- | --- | --- | --- |
| Happy | `Happy` | `jade_happy` | f_04_smile_blush | 眯眼笑 + 脸颊泛红 |
| Sad | `Sad` | `jade_sad` | f_05_sad_worried | 八字眉 + 含泪，担心用户 |
| Angry | `Angry` | — | （无专属） | 回退 `Idle`/`Think` |
| Think | `Think` | `jade_think` | f_01_normal | 不对称眉，沉思 |
| Surprise | `Surprise` | `jade_surprised` | f_03_surprised | 瞪眼张嘴 |
| Awkward | `Awkward` | — | （无专属） | 回退 `Idle` |
| Question | `Question` | — | （无专属） | 回退 `Think` |
| Neutral | `Idle` | `jade_idle` | f_06_neutral_blue | 平静蓝瞳默认态 |
| Curious | `Curious` | `jade_curious` | f_02_wink | 单眼 wink + 歪头 |

> 设定稿仅含 6 种表情，故 `Angry` / `Awkward` / `Question` 暂无专属美术，运行时回退到
> `Idle` 或 `Think`。后续可在 Cubism 中扩绘并新增对应 `exp3`。

### 4.3 各表情驱动的标准 Cubism 参数

| exp3 | 关键参数（Id → 目标值 / Blend） |
| --- | --- |
| `jade_happy` | ParamEyeLSmile=1 / ParamEyeRSmile=1 (Add)；ParamMouthForm=0.3；ParamTere=0.6（腮红）；ParamBrowL/R Y=0.1 |
| `jade_sad` | ParamBrowL/R Y=-0.4；ParamMouthForm=-0.3；ParamEyeL/R Open=0.7 (Overwrite)；ParamTear=0.25 |
| `jade_surprised` | ParamEyeL/R Open=1 (Overwrite)；ParamMouthOpenY=1 (Overwrite)；ParamBrowL/R Y=0.6 |
| `jade_idle` | ParamBreath=0.1；ParamAngleY=-0.03（轻微下视，专注聆听） |
| `jade_curious` | ParamEyeROpen=0 (Overwrite，wink)；ParamEyeLSmile=0.4；ParamAngleZ=0.12（歪头）；ParamEyeBallX=0.3 |
| `jade_think` | ParamBrowLY=0.15 / ParamBrowRY=-0.15（不对称）；ParamAngleX=-0.1；ParamEyeBallX=-0.2 |

参数 ID 与 `jade_maid.cdi3.json` / `jade_maid.model3.json` 的 `Groups` 保持一致；
当 Cubism 生成的 `moc3` 定义这些参数后，表情即可精确驱动网格。

---

## 5. 集成状态与补全步骤

### 5.1 当前状态（✅ 配置骨架已完成）

`packages/stage-ui/src/assets/live2d/models/jade_maid/`：

- `jade_maid.model3.json` — 入口，引用下列资源，内部引用**已校验自洽**
- `expressions/jade_{happy,sad,surprised,idle,curious,think}.exp3.json` — 6 表情
- `jade_maid.physics3.json` — 头发 + 裙摆物理
- `jade_maid.cdi3.json` — DisplayInfo 参数元数据
- `preview.jpg` / `reference_sheet.jpg` — 立绘与设定稿
- `jade_maid.zip` — 由 `scripts/build-jade-maid-zip.mjs` 打包（沿用 Hiyori 的 zip 预设惯例）
- 预设已注册：`displayModelsPresets` 中 `id: 'preset-live2d-jade'`，名称 `Jade (Maid)`

### 5.2 ⚠️ 缺失的二进制资产（沙箱无法自动生成）

| 文件 | 说明 | 生成方式 |
| --- | --- | --- |
| `jade_maid.moc3` | 模型几何/绑定（必需） | **Live2D Cubism Editor 4.x+/5.0** 从立绘切图导出 |
| `jade_maid_texture_00.png` | 贴图图集（必需） | 同上，从女仆立绘切分 |

> 这两份是 Live2D 专有二进制格式。最终的 moc3 + 贴图**必须由美术在 Cubism Editor 中导出**；
> 但"从立绘切图"这一步现已可自动化：若只有单张平图（如当前 `preview.jpg` / `reference_sheet.jpg`），
> 可先用 **`shitagaki-lab/see-through`**（SIGGRAPH 2026）把图拆成最多 23 个语义分层、遮挡补全、
> 深度排序的**分层 PSD**，再导入 Cubism Editor 绑参导出（详见 skill `live2d-character-skeleton` §8）。
> 当前沙箱没有 GUI / Cubism 运行时，无法自动产出真实 moc3。缺它们时选择该预设会加载
> `model3.json` 成功、但在实例化 `moc3` 时报错（优雅失败，不影响其它模型）。
>
> **关于"Live2D 自动化 MCP 服务器"（`J621111/live2d-automation`，MIT）**：它有**双重身份**——
> - 无真实 Cubism Editor 时，产出的是 **mock 中间包**（`.moc3` 占位、`ready_for_cubism_editor=false`），
>   仅作图像分析/分层参考，**不可当真**。
> - 给定真实 Cubism Editor 可执行文件（`--editor-path ... --native-gui-controller-mode execute`）时，
>   **真正驱动 Cubism Editor GUI 完成"导入 PSD → 套模板(自动绑参) → 导出真 MOC3"**，是端到端自动化最强方案
>   （详见 skill `live2d-character-skeleton` §8 路线 A）。

### 5.3 补全二进制（路线 A：Cubism，AIJADE 可直接加载）

> 路线对应 skill `live2d-character-skeleton` §8 的 **路线 A（四阶段自动化）**。Jade 走的是这条——
> 因为只有 Cubism 的 `.moc3`/`.model3.json` 能被 AIJADE 的 `DisplayModelFormat.Live2dZip` 加载。

0. **（可选，自动切图）** 若只有单张平图，先跑切图：
   ```bash
   # 用 skill 提供的包装（自动定位 see-through 仓库并调用）
   node <skill>/scripts/segment-see-through.mjs --image preview.jpg --char jade_maid
   # 产物：see-through 仓库 workspace/layerdiff_output/preview.psd（分层、可直接进 Cubism）
   # 若有现成分层 PSD/CLIP STUDIO 源，跳过此步，直接进 1。
   ```
   - **（可选）自动生表情参考**：若还想免去手绘表情参考，可先跑 §5.5 的 THA4（阶段 0）从这张立绘
     渲染出一套身份一致的表情 PNG，作为后续 Cubism 自动绑骨的表情 key（注意 NC 许可仅非商用）。
1. **（自动绑参+导出，接真实 Cubism）** 用 `J621111/live2d-automation` 的 Windows GUI 控制器
   驱动已安装的 Cubism Editor 5 完成导入→套模板(自动绑参)→导出真 moc3。本 skill 提供一键包装
   `auto-rig-export.mjs`：
   ```bash
   # PSD-only（推荐，阶段0已产出分层PSD）：
   node <skill>/scripts/auto-rig-export.mjs --char jade_maid \
       --psd output/jade_maid_real/jade_maid.psd \
       --editor-path "C:\Program Files\Live2D\Cubism5\Cubism Editor 5\CubismEditor5.exe"
   # 或先 dry_run 看生成的 PowerShell 脚本，不真动 Editor
   ```
   - 需本机装好 Cubism Editor 5 + Windows 桌面；`--editor-path` 缺省时只产出 mock 占位，不可用于生产。
   - 菜单序列写在 live2d-automation 的 `mcp_server/profiles/windows_cubism_default.json`，
     若校准失败看 `*_cubism_profile_calibration*.json` 按官方菜单路径微调。
   - 纯手工等价操作（无自动化时）：Cubism Editor 5 导入分层 PSD → `Auto Mesh Generator` /
     变形器的自动生成 / `Auto Standard Form`（5.0）/ `Auto Generation of Sway Motion`（5.1）→
     绑定至少 §4.3 的 Id → `文件 → 导出 → 导出为 moc3 模型`。
2. 导出产物 `jade_maid.moc3` 与 `jade_maid_texture_00.png` 放入 `jade_maid/`（覆盖占位）。
3. （可选）在 Cubism 中录制 `.motion3.json` 动作增强表现力。
4. 重新打包：
   ```bash
   node scripts/build-jade-maid-zip.mjs
   ```
5. 前端模型选择器选 `Jade (Maid)` 验证加载、表情与物理。

### 5.4 替代方案：路线 B（Inochi2D，完全开源，但 AIJADE 加载器不认）

若未来想**完全脱离 Live2D 专有许可**，可改用 **Inochi2D**（`Inochi2D/inochi2d`，BSD-2-Clause）：
用 `Inochi Creator`（开源 GUI 绑骨器）把分层 PSD 绑成 `.inp`/`.inx` 木偶。但需注意（详见 skill §0.1 / §8 路线 B）：

- **格式不兼容**：Inochi2D 的 `.inp`/`.inx` 与 Cubism 的 `.moc3` 是两套不同标准，**AIJADE 现有
  `Live2dZip` 加载器无法加载**，须新增 Inochi2D 渲染后端（改 `packages/stage-ui-live2d` 或新包），超出本文范围。
- **无全自动绑骨**：Inochi Creator 只有 GUI、无无头 CLI，从平图到 rigged puppet 须美术手工操作；
  不像路线 A 的 live2d-automation 能无人值守自动导出。
- **无 Live2D↔Inochi2D 生产级互转器**，按目标格式原生制作。

> 结论：Jade 若要"进 AIJADE 且全自动"，唯一现实路线是 **路线 A（专有 Cubism Editor 5）**；
> 路线 B 适合"自有 Web/游戏引擎里用、不在乎 AIJADE 兼容性"的纯开源场景。

---

### 5.5 可选增强：THA4 自动生成表情参考集（阶段 0，非商用）

若想从单张 Jade 立绘**全自动**拿到一套身份一致的表情/姿态参考图（免去手绘表情），可接入
**THA4（talking-head-anime-4，pkhungurn，WACV 2025）** 作为路线 A 前端的自动生图源
（详见 skill `live2d-character-skeleton` §0.2 / 阶段 0）：

- 给一张 512×512 RGBA 的 Jade 立绘，THA4 用 **45 维 pose 向量**渲染出
  `neutral / idle / happy / angry / surprise / sad / think / curious / blink /
  元音口型(mouth_aaa/iii/uuu/eee/ooo) / 歪头 / 转身 / 视线 / 呼吸` 等参考 PNG。
- ⚠️ THA4 **产出的是位图帧、不是 Live2D rig**，也不能替 Cubism 导出 `.moc3`；
  它只是"表情长什么样"的参考 key，喂给 Cubism 自动绑骨当表情参照。
- ⚠️ **许可边界**：THA4 **模型权重 CC BY-NC 4.0（非商业）**。本项目已确认为个人 / 非商用，可用；
  若将来商用或再分发，需隔离权重或换可商用方案。
- 运行（需 THA4 仓库 + 权重 + Nvidia GPU，Python 3.10 + PyTorch）：
  ```bash
  cd <tha4_repo>                       # 使 import tha4 可用；权重在 data/tha4/*.pt
  python <skill>/scripts/gen_character_references.py \
      --image preview.jpg --outdir ./jade_maid_refs --model-dir data/tha4 --device cuda
  # 产物：jade_maid_refs/{neutral,happy,...,mouth_aaa,...}.png + manifest.json
  ```
- 生成的 `jade_maid_refs/manifest.json` 含每个表情的 **45 维 pose 向量**，可与 §4.3 的 Cubism 参数
  对照映射，作为 Cubism 自动绑骨时的表情 key：
  `mouth_aaa↔ParamMouthOpenY`、`eyebrow_*↔ParamBrowLY/RY`、`neck_z↔ParamAngleZ`、
  `body_y↔ParamBodyAngleY`、`breathing↔ParamBreath`、`iris_rotation_x/y↔ParamEyeBallX/Y`。

> 注意：THA4 参考集**不替代** §5.3 步骤 0 的 see-through 切图（仍负责拆分层 PSD），也不改变
> "真 `.moc3` 由 Cubism Editor 导出"的结论。它让"全自动参考图→Live2D"中**"表情参考"这一步也自动化**，
> 与 see-through（自动切图）、live2d-automation（自动绑骨导出）共同把整条链推到全自动。

### 5.6 THA4 → Cubism 一键执行清单（Jade，本机有 GPU）

完整可照跑步骤、参数与排错见 skill runbook：
`live2d-character-skeleton/THA4_TO_CUBISM_JADE_RUNBOOK.md`。
按链路顺序摘要如下：

0. **前置**：Nvidia GPU + CUDA、THA4 仓库与权重（CC BY-NC，个人/非商用）、Jade 512×512 RGBA 平图、Cubism Editor 5、live2d-automation、AIJADE 项目。
1. **阶段 0（THA4 生参考集，全自动）**：
   ```bash
   cd <tha4_repo> && export PYTHONPATH="$PWD/src:$PYTHONPATH"
   python <skill>/scripts/gen_character_references.py --image jade_maid.png --outdir ./jade_maid_refs --model-dir data/tha4 --device cuda
   ```
   → 产出表情 PNG 集 + **`manifest.json`**（⚠️ 回传助手用于校准 §0.3，即 C 步骤）。
2. **阶段 1（see-through 切分层 PSD）**：把平图自动拆分层，作 Cubism 绑骨素材（THA4 不替代此步）。
3. **阶段 2+3（live2d-automation + Cubism 导出）**：Windows 上 `execute` 模式无人值守驱动 Cubism 导出真 `.moc3`+贴图+motions；按 §0.3 把同名义表情 key 绑到 `Param*`。
4. **阶段 4（AIJADE 打包）**：`build-live2d-zip` 打成 `Live2dZip` 预设并注册，AIJADE 按 `Emotion` 枚举播放对应 motion。
5. **校准（C，回传后由助手执行）**：拿阶段 0 的 `manifest.json` 真实 pose 向量校准 §0.3 映射表的"关键 pose 组"实际数值。

---

## 6. 文件清单（本次新增/修改）

| 路径 | 类型 | 说明 |
| --- | --- | --- |
| `packages/stage-ui/src/assets/live2d/models/jade_maid/jade_maid.model3.json` | 新增 | 模型入口 |
| `packages/stage-ui/src/assets/live2d/models/jade_maid/expressions/jade_*.exp3.json` | 新增 | 6 表情 |
| `packages/stage-ui/src/assets/live2d/models/jade_maid/jade_maid.physics3.json` | 新增 | 物理 |
| `packages/stage-ui/src/assets/live2d/models/jade_maid/jade_maid.cdi3.json` | 新增 | DisplayInfo |
| `packages/stage-ui/src/assets/live2d/models/jade_maid/preview.jpg` | 新增 | 立绘 |
| `packages/stage-ui/src/assets/live2d/models/jade_maid/reference_sheet.jpg` | 新增 | 设定稿 |
| `packages/stage-ui/src/assets/live2d/models/jade_maid.zip` | 新增 | 打包产物 |
| `packages/stage-ui/src/stores/display-models.ts` | 修改 | 注册 `Jade (Maid)` 预设 |
| `scripts/build-jade-maid-zip.mjs` | 新增 | 打包脚本 |
| `docs/content/zh-Hans/characters/jade-maid.md` | 新增 | 本文件 |
