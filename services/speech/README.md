# AIJADE 本地语音服务栈

本地 GPU 自托管的语音子系统：ASR（听）+ TTS（说），并打通"超人格化"双向情绪闭环。

## 架构

| 角色 | 服务 | 端口 | 端点 | 说明 |
|------|------|------|------|------|
| ASR | `sensevoice_asr_server.py` | 8000 | `POST /v1/audio/transcriptions` | FunASR/SenseVoiceSmall，50+ 语、原生情绪/事件/说话人、比 Whisper 快 ~15×；`verbose_json` 返回 `{text, language, emotion, event}` |
| TTS | `D:/项目/index-tts/tts_server.py` | 8765 | `POST /v1/audio/speech` | IndexTTS2 零样本音色克隆 + 情绪控制（`emo_text` / `emo_vector` / `voice_audio`） |
| TTS(可选) | CosyVoice 本地 `examples/llm/api_server.py` | 9000 | `POST /v1/audio/speech` | CosyVoice Instruct 情绪路径 |

所有端点都是 **OpenAI 兼容** 的，AIJADE 侧通过 `buildOpenAICompatibleProvider` 直接接入。

## 超人格化闭环

```
LLM 输出 <|ACT {"emotion":"happy"}|>
   ├─→ emotionsQueue.enqueue  → 驱动 avatar 表情（脸）
   └─→ currentTtsEmotionName  → IndexTTS2 emo_text / CosyVoice instruct → 声音带情绪

用户说话 → 音频流(Int16 PCM mono 16kHz)
   ├─→ xsai 流式转录 → 文本
   └─→ TransformStream 分叉 → 每句末包成 WAV → FunASR verbose_json
         → 解析 emotion → setUserEmotion
               ↓
         chat.ts getSystemPromptSupplement 注入 system prompt
         "[User emotional state] The user is currently speaking with a happy tone…"
               ↓
         LLM 据此调整回复语气（听者情绪→LLM，双向闭环）
停止监听 → clearUserEmotion() 防残留
```

## 快速启动

### Windows（本机）
```bat
services\speech\start.bat
```
脚本会先后拉起 SenseVoice ASR(:8000) 与 IndexTTS2 TTS(:8765)。
（funasr 已装进 `D:/项目/index-tts/.venv`，复用其 torch；若无独立 venv 则回退到该 venv。）

### Linux / Docker
```bash
cd services/speech
docker compose up --build      # 需要 nvidia container toolkit
```

### 手动（Python venv）
```bash
cd services/speech
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt        # 或：pip install funasr python-multipart（复用既有 torch）
python -m uvicorn sensevoice_asr_server:app --port 8000
```

## AIJADE 接线

1. **ASR**：设置 → providers → transcription → **funasr-transcription**，Base URL 填 `http://localhost:8000/v1`。
2. **TTS（IndexTTS2）**：设置 → providers → speech → **index-tts-vllm**，Base URL 填 `http://localhost:8765/v1`。LLM 的 `<|ACT {"emotion":...}|>` 会自动注入成 `emo_text`。
3. **TTS（CosyVoice 本地）**：设置 → providers → speech → **cosyvoice-local**，Base URL 填 `http://localhost:9000/v1`。

## 冒烟测试
```bash
cd services/speech
python smoke_test.py --sample 你的语音.wav --cosyvoice
# 不传 --sample 会自动生成 1 秒 440Hz 音做连通性验证
```

## 许可证提醒（商用前必读）

- **IndexTTS2**：bilibili 模型使用许可，**商用需联系 `indexspeech@bilibili.com`** 授权
- **CosyVoice**：官方声明"仅限学术研究"
- **FunASR / SenseVoiceSmall**：MIT 工具链，但**模型权重**另有《Model License Agreement》（ModelScope）
- **本地自托管不触发云服务条款**，但分发/商用前必须拿到上述授权
