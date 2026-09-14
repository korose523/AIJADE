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

<p align="center">Виртуальный персонаж на базе LLM, который работает в браузере, на рабочем столе и в кармане.</p>

<p align="center">
  <a href="../README.md">English</a> ·
  <a href="./README.zh-CN.md">简体中文</a> ·
  <a href="./README.ja-JP.md">日本語</a> ·
  <a href="./README.ko-KR.md">한국어</a> ·
  <a href="./README.vi.md">Tiếng Việt</a> ·
  <a href="./README.fr.md">Français</a>
</p>

---

## Что это

AIJADE — открытая платформа виртуальных персонажей. Достаточно указать поставщика LLM и персонажа, и вы получаете компаньона, который говорит, слушает, помнит и имеет лицо. **Одна кодовая база, три фронтенда, общий движок персонажа.**

Это не обёртка для чата вокруг одной модели. Интересное находится вокруг модели: сквозной голосовой конвейер, 3D-персонаж, реагирующий на внутреннее состояние, слой памяти, переживающий сессии, и агентный слой, который сам учится навыкам из разговора.

## Платформы

| Фронтенд | Назначение | Каталог |
| --- | --- | --- |
| **Веб** | Любой современный браузер | [`apps/stage-web`](../apps/stage-web) |
| **Рабочий стол** | Windows / macOS / Linux (Electron) | [`apps/stage-tamagotchi`](../apps/stage-tamagotchi) |
| **Мобильные** | iOS / Android | [`apps/stage-pocket`](../apps/stage-pocket) |
| **Сервер** | Служба Node.js, админ- и auth-интерфейсы | [`apps/server`](../apps/server), [`apps/ui-admin`](../apps/ui-admin), [`apps/ui-server-auth`](../apps/ui-server-auth) |

Все три фронтенда персонажа используют один общий слой интерфейса [`packages/stage-ui`](../packages/stage-ui), поэтому персонаж ведёт себя одинаково везде.

## Возможности

**Персонаж и сцена**
- Рендеринг VRM с `lookAt`, выражениями и blendshape ([`packages/stage-ui-three`](../packages/stage-ui-three)), а также поддержка Live2D и Spine
- Импорт MMD / PMX / PMD, запасной путь GLB / glTF, смешивание синтеза движения
- **Режим питомца на рабочем столе**: само окно Electron становится прозрачным, безрамочным, всегда поверх остальных — его можно перетаскивать, а настроение и близость отрисовываются из живого внутреннего состояния
- Голографический режим для прозрачных проекций

**Голос**
- Полнодуплексная речь: ASR на входе, TTS на выходе, единая точка входа
- Несколько движков TTS (локальный Kokoro, zero-shot IndexTTS2, адаптеры CosyVoice) за одним интерфейсом
- Синтез с учётом эмоций и распознавание эмоций в интонации пользователя
- Обнаружение слова активации и конвейер умной колонки без рук (активация → VAD → ASR → LLM → TTS)

**Разум**
- Сменные бэкенды памяти, включая хранилище Postgres/pgvector ([`packages/memory-pgvector`](../packages/memory-pgvector))
- Биомиметическая двухграфовая память: эпизодический опыт и убеждения с источниками ([`packages/memory-biomimetic`](../packages/memory-biomimetic))
- Непрерывный дрейф персоны под управлением аффективной динамики — настроение действительно имеет состояние, а не написано сценарием

**Агентный слой**
- Автоматическое создание навыков: обнаружение обучающего момента в разговоре, генерация, проверка и регистрация ([`packages/agent-skill-forge`](../packages/agent-skill-forge))
- Непрерывное обучение: циклы обратной связи позволяют зарегистрированным навыкам развиваться ([`packages/agent-continuous-learning`](../packages/agent-continuous-learning))
- Управление компьютером: по умолчанию dry-run, реальное управление через шов MCP ([`packages/agent-computer-use`](../packages/agent-computer-use))
- Мост, подключающий всё перечисленное к оркестратору чата ([`packages/agent-capabilities`](../packages/agent-capabilities))

**Экосистема**
- SDK плагинов с типизированным протоколом ([`packages/plugin-sdk`](../packages/plugin-sdk), [`packages/plugin-protocol`](../packages/plugin-protocol)) и готовые плагины для умного дома, медиа, шахмат, кодирующих агентов и браузера
- Мосты к чат-платформам: Discord, Telegram, Satori, Twitter
- Служба Minecraft и MCP-сервер управления компьютером в [`services/`](../services)
- Эксперимент с движком на Godot в [`engines/`](../engines)

## Технологический стек

| | Версия |
| --- | --- |
| Node.js | `>=22.0.0` |
| pnpm | `10.33.0` (закреплено в `packageManager`) |
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

Монорепозиторий pnpm workspace под управлением Turborepo. Версии зависимостей закреплены через catalog в [`pnpm-workspace.yaml`](../pnpm-workspace.yaml).

## Начало работы

Требуются **Node.js ≥ 22** и **pnpm 10.33.0** (`corepack enable` подхватит закреплённую версию).

```bash
pnpm install
```

`postinstall` собирает пакеты workspace, поэтому первая установка занимает время.

### Запуск

```bash
pnpm dev                  # веб-клиент
pnpm dev:tamagotchi       # приложение для рабочего стола (Electron)
pnpm dev:pocket:android   # мобильные, Android
pnpm dev:pocket:ios       # мобильные, iOS
pnpm dev:server           # серверная среда выполнения
pnpm dev:docs             # сайт документации
```

### Сборка

```bash
pnpm build                # все пакеты и приложения
pnpm build:web            # только веб-клиент
pnpm build:tamagotchi     # только приложение для рабочего стола
pnpm build:packages       # только пакеты workspace
```

### Проверки

```bash
pnpm typecheck            # проверка типов во всём проекте
pnpm lint                 # oxlint + eslint через moeru-lint
pnpm test:run             # модульные, визуальные и UI-тесты
```

## Структура репозитория

```
apps/         фронтенды и их бэкенды (веб, рабочий стол, мобильные, сервер, админка)
packages/     общие библиотеки — UI, персонаж, память, агент, модель, аудио, инструменты
services/     вспомогательные службы (речь, MCP управления компьютером, чат-мосты, Minecraft)
plugins/      собственные плагины на SDK плагинов
engines/      эксперименты с альтернативными движками
docs/         сайт документации, документация продукта и исследовательские заметки
```

## Документация

- [`ARCHITECTURE.md`](./ARCHITECTURE.md) — как устроена система
- [`FEATURES.md`](./FEATURES.md) — перечень возможностей
- [`AGENT_CAPABILITIES.md`](./AGENT_CAPABILITIES.md) — агентный слой возможностей
- [`COMPUTER_USE_INTEGRATION.md`](./COMPUTER_USE_INTEGRATION.md) — интеграция управления компьютером

## Лицензия

[MIT](../LICENSE).
