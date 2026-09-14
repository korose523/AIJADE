<picture>
  <source
    width="100%"
    srcset="./content/public/banner-dark-1280x640.avif"
    media="(prefers-color-scheme: dark)"
  />
  <source
    width="100%"
    srcset="./content/public/banner-light-1280x640.avif"
    media="(prefers-color-scheme: light), (prefers-color-scheme: no-preference)"
  />
  <img width="250" src="./content/public/banner-light-1280x640.avif" />
</picture>

<h1 align="center">AIJADE</h1>

<p align="center">Một nhân vật ảo chạy bằng LLM, hoạt động trên trình duyệt, máy tính để bàn và cả trong túi bạn.</p>

<p align="center">
  <a href="../README.md">English</a> ·
  <a href="./README.zh-CN.md">简体中文</a> ·
  <a href="./README.ja-JP.md">日本語</a> ·
  <a href="./README.ko-KR.md">한국어</a> ·
  <a href="./README.ru-RU.md">Русский</a> ·
  <a href="./README.fr.md">Français</a>
</p>

---

## Đây là gì

AIJADE là một nền tảng nhân vật ảo mã nguồn mở. Bạn đưa vào một nhà cung cấp LLM và một nhân vật, bạn nhận được một người bạn đồng hành biết nói, biết nghe, biết ghi nhớ và có gương mặt. **Một cơ sở mã, ba giao diện, dùng chung một bộ máy nhân vật.**

Đây không phải một lớp bọc trò chuyện quanh một mô hình duy nhất. Phần thú vị nằm ở xung quanh mô hình: một đường ống giọng nói chạy trọn vẹn từ đầu đến cuối, một nhân vật 3D phản ứng theo trạng thái nội tại, một tầng ký ức tồn tại qua nhiều phiên, và một tầng tác tử có thể tự học kỹ năng từ hội thoại.

## Nền tảng

| Giao diện | Nền tảng | Thư mục |
| --- | --- | --- |
| **Web** | Mọi trình duyệt hiện đại | [`apps/stage-web`](../apps/stage-web) |
| **Máy tính để bàn** | Windows / macOS / Linux (Electron) | [`apps/stage-tamagotchi`](../apps/stage-tamagotchi) |
| **Di động** | iOS / Android | [`apps/stage-pocket`](../apps/stage-pocket) |
| **Máy chủ** | Dịch vụ Node.js, giao diện quản trị và xác thực | [`apps/server`](../apps/server), [`apps/ui-admin`](../apps/ui-admin), [`apps/ui-server-auth`](../apps/ui-server-auth) |

Cả ba giao diện nhân vật đều dùng chung một tầng UI [`packages/stage-ui`](../packages/stage-ui), nên nhân vật tạo một lần sẽ hành xử giống nhau ở mọi nơi.

## Điểm nổi bật

**Nhân vật và sân khấu**
- Kết xuất mô hình VRM với `lookAt`, biểu cảm và blendshape ([`packages/stage-ui-three`](../packages/stage-ui-three)), hỗ trợ cả Live2D và Spine
- Nhập MMD / PMX / PMD, dự phòng GLB / glTF, và pha trộn tổng hợp chuyển động
- **Chế độ thú cưng trên màn hình**: bản thân cửa sổ Electron trở thành một chú thú cưng trong suốt, không viền, luôn nổi trên cùng — kéo được, với tâm trạng và độ thân thiết được kết xuất từ trạng thái nội tại trực tiếp
- Chế độ ảnh ba chiều cho các thiết lập chiếu trong suốt

**Giọng nói**
- Giọng nói song công hoàn toàn: ASR vào, TTS ra, gom về một điểm vào duy nhất
- Nhiều bộ máy TTS (Kokoro cục bộ, IndexTTS2 zero-shot, bộ chuyển đổi CosyVoice) sau một giao diện
- Tổng hợp có nhận biết cảm xúc, và nhận diện cảm xúc trong giọng điệu người dùng
- Phát hiện từ đánh thức và đường ống loa thông minh rảnh tay (đánh thức → VAD → ASR → LLM → TTS)

**Tâm trí**
- Các backend ký ức có thể thay thế, bao gồm kho Postgres/pgvector ([`packages/memory-pgvector`](../packages/memory-pgvector))
- Ký ức hai đồ thị phỏng sinh học: trải nghiệm tình huống và niềm tin có nguồn chứng cứ ([`packages/memory-biomimetic`](../packages/memory-biomimetic))
- Sự trôi dạt nhân cách liên tục do động lực học cảm xúc dẫn dắt — tâm trạng thực sự có trạng thái chứ không phải do kịch bản

**Tầng tác tử**
- Tự động tạo kỹ năng: phát hiện khoảnh khắc có thể dạy trong hội thoại, sinh ra, kiểm định rồi đăng ký ([`packages/agent-skill-forge`](../packages/agent-skill-forge))
- Học liên tục: vòng phản hồi giúp kỹ năng đã đăng ký tiến hóa ([`packages/agent-continuous-learning`](../packages/agent-continuous-learning))
- Điều khiển máy tính: mặc định là backend dry-run, điều khiển thật qua đường nối MCP ([`packages/agent-computer-use`](../packages/agent-computer-use))
- Tầng cầu nối đưa toàn bộ các khả năng trên vào bộ điều phối hội thoại ([`packages/agent-capabilities`](../packages/agent-capabilities))

**Hệ sinh thái**
- SDK plugin với giao thức có kiểu ([`packages/plugin-sdk`](../packages/plugin-sdk), [`packages/plugin-protocol`](../packages/plugin-protocol)) và các plugin sẵn có cho nhà thông minh, truyền thông, cờ, tác tử lập trình và trình duyệt
- Cầu nối nền tảng trò chuyện: Discord, Telegram, Satori, Twitter
- Dịch vụ Minecraft và máy chủ MCP điều khiển máy tính trong [`services/`](../services)
- Thử nghiệm bộ máy Godot trong [`engines/`](../engines)

## Ngăn xếp công nghệ

| | Phiên bản |
| --- | --- |
| Node.js | `>=22.0.0` |
| pnpm | `10.33.0` (ghim qua `packageManager`) |
| Vue | `3.5.32` |
| Vite | `8.0.8` |
| TypeScript | `5.9.3` |
| Electron | `41.2.1` |
| Pinia | `3.0.4` |
| Vue Router | `5.0.4` |
| UnoCSS | `66.6.8` |
| Vitest | `4.1.4` |
| Turbo | `2.9.6` |
| tsdown | `0.21.9` |
| oxlint | `1.60.0` |

Monorepo pnpm workspace quản lý bằng Turborepo. Phiên bản phụ thuộc được ghim qua catalog trong [`pnpm-workspace.yaml`](../pnpm-workspace.yaml).

## Bắt đầu

Cần **Node.js ≥ 22** và **pnpm 10.33.0** (`corepack enable` sẽ dùng đúng phiên bản đã ghim).

```bash
pnpm install
```

`postinstall` sẽ build các gói trong workspace, nên lần cài đầu tiên mất khá lâu.

### Chạy

```bash
pnpm dev                  # ứng dụng web
pnpm dev:tamagotchi       # ứng dụng máy tính để bàn (Electron)
pnpm dev:pocket:android   # di động Android
pnpm dev:pocket:ios       # di động iOS
pnpm dev:server           # runtime máy chủ
pnpm dev:docs             # trang tài liệu
```

### Build

```bash
pnpm build                # toàn bộ gói và ứng dụng
pnpm build:web            # chỉ ứng dụng web
pnpm build:tamagotchi     # chỉ ứng dụng máy tính để bàn
pnpm build:packages       # chỉ các gói workspace
```

### Kiểm tra

```bash
pnpm typecheck            # kiểm tra kiểu toàn bộ
pnpm lint                 # oxlint + eslint qua moeru-lint
pnpm test:run             # bộ kiểm thử đơn vị / hình ảnh / UI
```

## Bố cục kho mã

```
apps/         các giao diện và backend của chúng (web, máy tính để bàn, di động, máy chủ, quản trị)
packages/     thư viện dùng chung — UI, nhân vật, ký ức, tác tử, mô hình, âm thanh, công cụ
services/     dịch vụ phụ (giọng nói, MCP điều khiển máy tính, cầu nối trò chuyện, Minecraft)
plugins/      plugin bên thứ nhất xây trên SDK plugin
engines/      thử nghiệm bộ máy thay thế
docs/         trang tài liệu, tài liệu sản phẩm và ghi chú nghiên cứu
```

## Tài liệu

- [`ARCHITECTURE.md`](./ARCHITECTURE.md) — hệ thống được ghép lại như thế nào
- [`FEATURES.md`](./FEATURES.md) — danh mục tính năng
- [`AGENT_CAPABILITIES.md`](./AGENT_CAPABILITIES.md) — tầng năng lực tác tử
- [`COMPUTER_USE_INTEGRATION.md`](./COMPUTER_USE_INTEGRATION.md) — tích hợp điều khiển máy tính

## Giấy phép

[MIT](../LICENSE).
