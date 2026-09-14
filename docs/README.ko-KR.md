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

<p align="center">브라우저에서도, 데스크톱에서도, 주머니 속에서도 동작하는 LLM 기반 버추얼 캐릭터.</p>

<p align="center">
  <a href="../README.md">English</a> ·
  <a href="./README.zh-CN.md">简体中文</a> ·
  <a href="./README.ja-JP.md">日本語</a> ·
  <a href="./README.ru-RU.md">Русский</a> ·
  <a href="./README.vi.md">Tiếng Việt</a> ·
  <a href="./README.fr.md">Français</a>
</p>

---

## 무엇인가

AIJADE는 오픈소스 버추얼 캐릭터 플랫폼입니다. LLM 제공자와 캐릭터를 정해 주면, 말하고 듣고 기억하며 얼굴을 가진 동반자가 됩니다. **하나의 코드베이스, 세 개의 프런트엔드, 공통의 캐릭터 엔진**입니다.

단일 모델을 감싼 채팅 래퍼가 아닙니다. 흥미로운 부분은 모델 바깥에 있습니다. 끝에서 끝까지 이어지는 음성 파이프라인, 내부 상태에 반응하는 3D 캐릭터, 세션을 넘어 남는 기억 계층, 그리고 대화에서 스킬을 스스로 배우는 에이전트 계층입니다.

## 플랫폼

| 프런트엔드 | 대상 | 디렉터리 |
| --- | --- | --- |
| **웹** | 최신 브라우저 | [`apps/stage-web`](../apps/stage-web) |
| **데스크톱** | Windows / macOS / Linux (Electron) | [`apps/stage-tamagotchi`](../apps/stage-tamagotchi) |
| **모바일** | iOS / Android | [`apps/stage-pocket`](../apps/stage-pocket) |
| **서버** | Node.js 서비스, 관리·인증 UI | [`apps/server`](../apps/server), [`apps/ui-admin`](../apps/ui-admin), [`apps/ui-server-auth`](../apps/ui-server-auth) |

세 개의 캐릭터 프런트엔드는 동일한 공유 UI 계층 [`packages/stage-ui`](../packages/stage-ui)를 사용하므로, 한 번 만든 캐릭터가 모든 플랫폼에서 같게 동작합니다.

## 주요 기능

**캐릭터와 무대**
- `lookAt`, 표정, 블렌드셰이프를 지원하는 VRM 렌더링([`packages/stage-ui-three`](../packages/stage-ui-three)), Live2D와 Spine 지원
- MMD / PMX / PMD 가져오기, GLB / glTF 폴백, 모션 합성 블렌딩
- **데스크톱 펫 모드**: Electron 창 자체가 투명·무테두리·항상 위 펫이 되며 드래그할 수 있습니다. 기분과 친밀도는 실시간 내부 상태에서 렌더링됩니다
- 투명 프로젝션을 위한 홀로그램 모드

**음성**
- 전이중 음성: ASR 입력, TTS 출력을 단일 진입점으로 통합
- 여러 TTS 엔진(로컬 Kokoro, 제로샷 IndexTTS2, CosyVoice 어댑터)을 하나의 인터페이스로
- 감정 반영 합성과 사용자 말투의 감정 인식
- 웨이크워드 감지와 핸즈프리 스마트 스피커 파이프라인(웨이크 → VAD → ASR → LLM → TTS)

**마음**
- 교체 가능한 기억 백엔드(Postgres/pgvector 구현 포함)([`packages/memory-pgvector`](../packages/memory-pgvector))
- 생체모방 이중 그래프 기억: 에피소드 경험과 근거 있는 신념([`packages/memory-biomimetic`](../packages/memory-biomimetic))
- 정동 역학이 이끄는 지속적 페르소나 드리프트. 기분이 대본이 아니라 실제 상태를 가집니다

**에이전트 계층**
- 자동 스킬 생성: 대화에서 가르칠 만한 순간을 감지해 생성·검증·등록([`packages/agent-skill-forge`](../packages/agent-skill-forge))
- 지속 학습: 피드백 루프로 등록된 스킬이 진화([`packages/agent-continuous-learning`](../packages/agent-continuous-learning))
- 컴퓨터 조작: 기본은 드라이런 백엔드, 실제 조작은 MCP 이음매로([`packages/agent-computer-use`](../packages/agent-computer-use))
- 브리지 계층: 위 기능을 동형으로 채팅 오케스트레이터에 연결([`packages/agent-capabilities`](../packages/agent-capabilities))

**생태계**
- 플러그인 SDK와 타입 지정 프로토콜([`packages/plugin-sdk`](../packages/plugin-sdk), [`packages/plugin-protocol`](../packages/plugin-protocol)), 스마트홈·미디어·체스·코딩 에이전트·브라우저 플러그인 동봉
- 채팅 플랫폼 연동: Discord, Telegram, Satori, Twitter
- [`services/`](../services)의 Minecraft 서비스와 컴퓨터 조작 MCP 서버
- [`engines/`](../engines)의 Godot 엔진 실험

## 기술 스택

| | 버전 |
| --- | --- |
| Node.js | `>=22.0.0` |
| pnpm | `10.33.0` (`packageManager`로 고정) |
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

pnpm workspace 모노레포를 Turborepo로 관리합니다. 의존성 버전은 [`pnpm-workspace.yaml`](../pnpm-workspace.yaml)의 catalog로 고정됩니다.

## 시작하기

**Node.js ≥ 22** 와 **pnpm 10.33.0** 이 필요합니다(`corepack enable` 로 고정 버전을 사용합니다).

```bash
pnpm install
```

`postinstall` 이 workspace 패키지를 빌드하므로 첫 설치에는 시간이 걸립니다.

### 실행

```bash
pnpm dev                  # 웹 클라이언트
pnpm dev:tamagotchi       # 데스크톱 앱 (Electron)
pnpm dev:pocket:android   # 모바일 Android
pnpm dev:pocket:ios       # 모바일 iOS
pnpm dev:server           # 백엔드 런타임
pnpm dev:docs             # 문서 사이트
```

### 빌드

```bash
pnpm build                # 모든 패키지와 앱
pnpm build:web            # 웹 클라이언트만
pnpm build:tamagotchi     # 데스크톱 앱만
pnpm build:packages       # workspace 패키지만
```

### 검사

```bash
pnpm typecheck            # 전체 타입 검사
pnpm lint                 # moeru-lint 를 통한 oxlint + eslint
pnpm test:run             # 단위 / 비주얼 / UI 테스트
```

## 저장소 구조

```
apps/         각 프런트엔드와 그 백엔드 (웹·데스크톱·모바일·서버·관리)
packages/     공유 라이브러리——UI, 캐릭터, 기억, 에이전트, 모델, 오디오, 도구
services/     부가 서비스 (음성, 컴퓨터 조작 MCP, 채팅 연동, Minecraft)
plugins/      플러그인 SDK 기반 자체 플러그인
engines/      대체 엔진 실험
docs/         문서 사이트, 제품 문서, 연구 노트
```

## 문서

- [`ARCHITECTURE.md`](./ARCHITECTURE.md) — 시스템 전체 구조
- [`FEATURES.md`](./FEATURES.md) — 기능 목록
- [`AGENT_CAPABILITIES.md`](./AGENT_CAPABILITIES.md) — 에이전트 능력 계층
- [`COMPUTER_USE_INTEGRATION.md`](./COMPUTER_USE_INTEGRATION.md) — 컴퓨터 조작 통합

## 라이선스

[MIT](../LICENSE).
