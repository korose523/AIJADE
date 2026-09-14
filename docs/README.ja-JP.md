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

<p align="center">ブラウザでも、デスクトップでも、ポケットの中でも動く LLM 駆動のバーチャルキャラクター。</p>

<p align="center">
  <a href="../README.md">English</a> ·
  <a href="./README.zh-CN.md">简体中文</a> ·
  <a href="./README.ko-KR.md">한국어</a> ·
  <a href="./README.ru-RU.md">Русский</a> ·
  <a href="./README.vi.md">Tiếng Việt</a> ·
  <a href="./README.fr.md">Français</a>
</p>

---

## これは何か

AIJADE はオープンソースのバーチャルキャラクター基盤です。LLM プロバイダとキャラクターを用意すれば、話し、聞き、記憶し、姿を持つコンパニオンが手に入ります。**ひとつのコードベース、三つのフロントエンド、共通のキャラクターエンジン**です。

単一モデルを包んだチャットラッパーではありません。面白いのはモデルの外側です。端から端まで通った音声パイプライン、内部状態に反応する 3D キャラクター、セッションをまたいで残る記憶層、そして会話からスキルを学ぶエージェント層。

## プラットフォーム

| フロントエンド | 対象 | ディレクトリ |
| --- | --- | --- |
| **Web** | モダンブラウザ | [`apps/stage-web`](../apps/stage-web) |
| **デスクトップ** | Windows / macOS / Linux（Electron） | [`apps/stage-tamagotchi`](../apps/stage-tamagotchi) |
| **モバイル** | iOS / Android | [`apps/stage-pocket`](../apps/stage-pocket) |
| **サーバー** | Node.js サービス、管理・認証 UI | [`apps/server`](../apps/server)、[`apps/ui-admin`](../apps/ui-admin)、[`apps/ui-server-auth`](../apps/ui-server-auth) |

三つのキャラクター用フロントエンドは共通の UI レイヤー [`packages/stage-ui`](../packages/stage-ui) をマウントするため、一度作ったキャラクターはどの端末でも同じ挙動になります。

## 主な機能

**キャラクターとステージ**
- `lookAt`・表情・ブレンドシェイプに対応した VRM 描画（[`packages/stage-ui-three`](../packages/stage-ui-three)）、Live2D と Spine にも対応
- MMD / PMX / PMD の読み込み、GLB / glTF フォールバック、モーション合成のブレンド
- **デスクトップペットモード**：Electron のウィンドウ自体が透過・枠なし・常時手前のペットになり、ドラッグ可能。機嫌と親密度はリアルタイムの内部状態から描画されます
- 透過投影向けのホログラムモード

**音声**
- 全二重音声：ASR 入力、TTS 出力を単一の入口に集約
- 複数の TTS エンジン（ローカル Kokoro、ゼロショット IndexTTS2、CosyVoice アダプタ）を単一インターフェースで
- 感情を反映した合成と、ユーザーの口調の感情検出
- ウェイクワード検出とハンズフリーのスマートスピーカーパイプライン（ウェイク → VAD → ASR → LLM → TTS）

**心**
- 差し替え可能な記憶バックエンド（Postgres/pgvector 実装を含む）（[`packages/memory-pgvector`](../packages/memory-pgvector)）
- 生体模倣の二重グラフ記憶：エピソード経験と、根拠のある信念（[`packages/memory-biomimetic`](../packages/memory-biomimetic)）
- 感情力学に駆動される継続的なペルソナの揺らぎ。機嫌は台本ではなく本当に状態を持ちます

**エージェント層**
- 自動スキル作成：会話から教えられる瞬間を検出し、生成・検証・登録（[`packages/agent-skill-forge`](../packages/agent-skill-forge)）
- 継続学習：フィードバックループで登録済みスキルが進化（[`packages/agent-continuous-learning`](../packages/agent-continuous-learning)）
- コンピュータ操作：既定はドライランバックエンド、実操作は MCP の接合部から（[`packages/agent-computer-use`](../packages/agent-computer-use)）
- ブリッジ層：上記を同型のままチャットオーケストレータへ接続（[`packages/agent-capabilities`](../packages/agent-capabilities)）

**エコシステム**
- プラグイン SDK と型付きプロトコル（[`packages/plugin-sdk`](../packages/plugin-sdk)、[`packages/plugin-protocol`](../packages/plugin-protocol)）。スマートホーム、メディア、チェス、コーディングエージェント、ブラウザ向けプラグインを同梱
- チャット連携：Discord、Telegram、Satori、Twitter
- [`services/`](../services) の Minecraft サービスとコンピュータ操作用 MCP サーバー
- [`engines/`](../engines) の Godot エンジン実験

## 技術スタック

| | バージョン |
| --- | --- |
| Node.js | `>=22.0.0` |
| pnpm | `10.33.0`（`packageManager` で固定） |
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

pnpm workspace のモノレポを Turborepo で管理しています。依存バージョンは [`pnpm-workspace.yaml`](../pnpm-workspace.yaml) の catalog で固定されます。

## はじめに

**Node.js ≥ 22** と **pnpm 10.33.0** が必要です（`corepack enable` で固定版が使われます）。

```bash
pnpm install
```

`postinstall` が workspace のパッケージをビルドするため、初回のインストールは時間がかかります。

### 実行

```bash
pnpm dev                  # Web クライアント
pnpm dev:tamagotchi       # デスクトップアプリ（Electron）
pnpm dev:pocket:android   # モバイル Android
pnpm dev:pocket:ios       # モバイル iOS
pnpm dev:server           # バックエンド
pnpm dev:docs             # ドキュメントサイト
```

### ビルド

```bash
pnpm build                # すべてのパッケージとアプリ
pnpm build:web            # Web クライアントのみ
pnpm build:tamagotchi     # デスクトップアプリのみ
pnpm build:packages       # workspace パッケージのみ
```

### チェック

```bash
pnpm typecheck            # 全体の型検査
pnpm lint                 # moeru-lint 経由で oxlint + eslint
pnpm test:run             # ユニット / ビジュアル / UI テスト
```

## リポジトリ構成

```
apps/         各フロントエンドとそのバックエンド（Web・デスクトップ・モバイル・サーバー・管理）
packages/     共有ライブラリ——UI、キャラクター、記憶、エージェント、モデル、音声、ツール
services/     サイドサービス（音声、コンピュータ操作 MCP、チャット連携、Minecraft）
plugins/      プラグイン SDK によるファーストパーティ製プラグイン
engines/      代替エンジンの実験
docs/         ドキュメントサイト、製品ドキュメント、研究ノート
```

## ドキュメント

- [`ARCHITECTURE.md`](./ARCHITECTURE.md) — システム全体の構成
- [`FEATURES.md`](./FEATURES.md) — 機能一覧
- [`AGENT_CAPABILITIES.md`](./AGENT_CAPABILITIES.md) — エージェント能力層
- [`COMPUTER_USE_INTEGRATION.md`](./COMPUTER_USE_INTEGRATION.md) — コンピュータ操作の統合

## ライセンス

[MIT](../LICENSE)。
