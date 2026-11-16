# AIJADE 本地语音服务

AIJADE 自有的 Python 标准库 HTTP 服务，独立启动，不读取或启动 MOSAIC、DSH、AstrBot 或第三方插件。此目录实现本地服务协议；语音与模型能力分开报告。

- `/tts`：macOS 已有 `say` 生成 AIFF，再由已有 `afconvert` 转成实际 PCM WAV。可通过 `--voice` 选择已安装的系统音色。这是系统合成，未经本项目训练，也不证明专属音色训练完成。接受 `emotion` 以兼容现有协议，但不声称系统音色应用了该情绪。
- `/transcribe`：仅在提供已有本地 `--asr-model` 目录时，首次请求惰性加载 faster-whisper，CPU int8、2 线程。`local_files_only=True`，不在启动或请求中下载模型。模型路径和服务状态目录必须位于所选 AIJADE 工作区内。
- `/align`、`/sing`：本服务尚未实现，明确返回 HTTP 503。不会生成伪对齐时间，也不会把普通朗读当歌声。
- `/health`：区分配置、命令可用、模型已加载和实际请求曾成功；未调用的引擎不写成已验证。健康响应不返回私人路径或音频。

## 启动

以下命令在 Mac 的 AIJADE 仓库内前台运行，按 Ctrl+C 停止。服务只允许 loopback 地址，不建立后台常驻或自动启动任务。

```sh
/Volumes/Untitled/AIJADE/.runtime/run-local.sh /usr/bin/python3 \
  tools/companion-services/server.py \
  --workspace /Volumes/Untitled/AIJADE \
  --state-dir /Volumes/Untitled/AIJADE/.runtime/companion-services \
  --host 127.0.0.1 --port 8796
```

管理员将现有“本地语音”路由地址设为 `http://127.0.0.1:8796`，健康接口使用 `/health`。不需要 MOSAIC 的语音服务。只启用已具备的路由；对齐和歌声不要指向本服务并标为就绪。

如需要本地 ASR，使用已安装 faster-whisper 的项目环境启动，并额外传入 `--asr-model /Volumes/Untitled/AIJADE/.../已有模型目录`。这是包含 `model.bin`、`tokenizer.json` 和 `config.json` 的本地 CTranslate2 模型目录，不是 Hub 仓库名；缺少本地 tokenizer 时直接拒绝，防止库走在线回退。CLI 启动还强制本进程的 Hub 离线模式。可选依赖版本见 `requirements-asr.txt`；安装依赖和提供模型是独立步骤，不会由服务请求触发。ASR 取消在模型输出片段之间协作处理；单个模型计算片段不保证即时中断。

## 协议与边界

```text
GET /health
POST /tts         {"text":"你好","emotion":"neutral"} -> audio/wav
POST /transcribe  {"wav_b64":"...","language":"Chinese"} -> {"text":"...","language":"zh","audio_s":...}
POST /align       -> 503 NOT_IMPLEMENTED
POST /sing        -> 503 NOT_IMPLEMENTED
```

仅接受所列字段，拒绝重复 JSON 键、错误类型、空文本、NUL 和超限输入。文本上限 2,000 字符；WAV 上限 4 MiB、两分钟，须为完整 PCM。语言为 `auto`、`Chinese`、`English`、`Japanese`、`Korean`。长文合成若超过音频上限会明确失败，调用方应分段，服务不会静默截断。

HTTP 正文上限 6 MiB，最多同时运行两项请求。系统命令没有 shell，文本经项目内临时文件传递。TTS 总时限默认 30 秒、最高 120 秒；超时、断开连接或停机时，只终止本请求启动的子进程，并清理临时文件。正文和音频不写请求日志。ASR 未配置、缺依赖、模型加载失败与运行失败分别返回明确 JSON 错误。

## 验证

```sh
/Volumes/Untitled/AIJADE/.runtime/run-local.sh /usr/bin/python3 -B \
  -m unittest discover -s tools/companion-services -p 'test_*.py' -v
```

测试使用真实 loopback HTTP、合成语音/ASR替身和本请求拥有的真实短命子进程，覆盖输入验证、可配置与已加载边界、明确失败、断开取消、超时及临时清理。它们不代表真实用户音色训练、ASR准确率或论文实验结果。实际系统语音和已配置模型应分别保留本地运行回执。
