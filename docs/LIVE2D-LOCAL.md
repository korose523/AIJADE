# 在本机使用 Live2D 皮肤

浏览器舞台可使用本机安装的 Live2D 模型。Mac 上的大肥鱼配置位于 AIJADE 工作区的 `.runtime/live2d/`，采用作者原有文件名和目录结构。完整模型和原画 PSD 受作者分发条款约束，请从作者原始发布渠道取得素材。大肥鱼（DeepSeek-chan）的原画及拆分由神宫凉子制作，Live2D 建模由霓虹猫_NeonNeko 完成。

## 启用

沿用现有 PostgreSQL 和 AIJADE 登录配置，在 `AIJADE-next` 根目录运行。把 `AIJADE_WORKSPACE_ROOT` 设为同时包含本仓库和 `.runtime` 的绝对路径。

```bash
export AIJADE_WORKSPACE_ROOT=/Volumes/Untitled/AIJADE
export Live2D__Root="$AIJADE_WORKSPACE_ROOT/.runtime/live2d"
export ASPNETCORE_URLS=http://127.0.0.1:5050
tools/run-companion.sh
```

访问本机地址，登录后打开聊天舞台。设置中的“模型文件地址”留空时读取 `.runtime/live2d/active.json` 来选择默认皮肤。有显式模型地址时，舞台使用该选择。清空旧地址并重新打开聊天页即可切回本机默认皮肤。模型成功显示后，舞台左上方会显示作者署名。

## 本机目录

- `active.json` 指向 `./model/` 内的 `.model3.json`。
- `model/` 包含原始模型以及与模型同级的 `aijade-live2d.json`。后者配置署名、动作、表情别名、最大纹理尺寸和模型专用的物理输入参数。大肥鱼配置将纹理上传尺寸上限设为 2048，磁盘上的原始纹理保持原尺寸，最长边为 8192 像素。
- `runtime/` 包含版本匹配的 Cubism Core、AIJADE 适配 bundle 和着色器。构建方法见 [Live2D 适配器](../tools/live2d-bundle/README.md)。

Cubism 的单缓冲打包模式最多容纳 36 组不同的裁剪蒙版。大肥鱼模型包含 49 组。默认超限路径用高精度模式，每次绘制裁剪部件前重绘所需蒙版。已经通过本机画面对照的模型可以在 `aijade-live2d.json` 中设置 `"maskMode": "packed"`，让 37 至 64 组蒙版使用两张 768 × 768 缓冲。使用 Cubism 高级混合的模型及不满足容量或图形能力条件的设备采用各自的默认路径。移除该配置或设为 `"high-precision"` 可恢复原高精度路径，重新进入聊天页后生效。[Cubism Web 蒙版说明](https://docs.live2d.com/en/cubism-sdk-manual/ow-sdk-mask-premake-web/)

模型、Core 和着色器由本机 HTTP 同源路由提供。舞台遇到缺失资源或 WebGL 初始化失败时显示内置头像，并在舞台提示中标明回退原因。Live2D 是陪伴产品的显示能力。学位论文第七章的正式场景证据使用其独立的 Godot 后端与验收流程。
