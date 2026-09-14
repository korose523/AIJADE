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

<p align="center">Un personnage virtuel propulsé par un LLM, dans votre navigateur, sur votre bureau et dans votre poche.</p>

<p align="center">
  <a href="../README.md">English</a> ·
  <a href="./README.zh-CN.md">简体中文</a> ·
  <a href="./README.ja-JP.md">日本語</a> ·
  <a href="./README.ko-KR.md">한국어</a> ·
  <a href="./README.ru-RU.md">Русский</a> ·
  <a href="./README.vi.md">Tiếng Việt</a>
</p>

---

## Présentation

AIJADE est une plateforme open source de personnages virtuels. Fournissez un fournisseur de LLM et un personnage, et vous obtenez un compagnon qui parle, écoute, se souvient et possède un visage. **Une seule base de code, trois interfaces, un moteur de personnage commun.**

Ce n'est pas une surcouche de chat autour d'un modèle unique. L'intérêt se situe autour du modèle : une chaîne vocale complète de bout en bout, un personnage 3D qui réagit à son état interne, une couche de mémoire qui survit d'une session à l'autre, et une couche d'agents capable d'apprendre de nouvelles compétences à partir de la conversation.

## Plateformes

| Interface | Cible | Dossier |
| --- | --- | --- |
| **Web** | Tout navigateur moderne | [`apps/stage-web`](../apps/stage-web) |
| **Bureau** | Windows / macOS / Linux (Electron) | [`apps/stage-tamagotchi`](../apps/stage-tamagotchi) |
| **Mobile** | iOS / Android | [`apps/stage-pocket`](../apps/stage-pocket) |
| **Serveur** | Service Node.js, interfaces d'administration et d'authentification | [`apps/server`](../apps/server), [`apps/ui-admin`](../apps/ui-admin), [`apps/ui-server-auth`](../apps/ui-server-auth) |

Les trois interfaces de personnage partagent la même couche d'interface [`packages/stage-ui`](../packages/stage-ui) : un personnage créé une fois se comporte de la même manière partout.

## Points forts

**Personnage et scène**
- Rendu de modèles VRM avec `lookAt`, expressions et blend shapes ([`packages/stage-ui-three`](../packages/stage-ui-three)), ainsi que la prise en charge de Live2D et Spine
- Import MMD / PMX / PMD, repli GLB / glTF et mélange de synthèse de mouvement
- **Mode animal de bureau** : la fenêtre Electron elle-même devient un compagnon transparent, sans cadre et toujours au premier plan — déplaçable, avec humeur et intimité rendues à partir de l'état interne en direct
- Mode hologramme pour les installations à projection transparente

**Voix**
- Parole en duplex intégral : ASR en entrée, TTS en sortie, derrière un point d'entrée unique
- Plusieurs moteurs TTS (Kokoro local, IndexTTS2 zero-shot, adaptateurs CosyVoice) derrière une seule interface
- Synthèse sensible aux émotions et détection des émotions dans l'intonation de l'utilisateur
- Détection de mot d'activation et chaîne d'enceinte intelligente mains libres (activation → VAD → ASR → LLM → TTS)

**Esprit**
- Backends de mémoire interchangeables, dont un stockage Postgres/pgvector ([`packages/memory-pgvector`](../packages/memory-pgvector))
- Mémoire biomimétique à double graphe : expérience épisodique et croyances sourcées ([`packages/memory-biomimetic`](../packages/memory-biomimetic))
- Dérive continue de la persona pilotée par la dynamique affective : l'humeur a réellement un état, elle n'est pas scénarisée

**Couche d'agents**
- Création automatique de compétences : détecter un moment propice dans la conversation, générer, valider et enregistrer ([`packages/agent-skill-forge`](../packages/agent-skill-forge))
- Apprentissage continu : des boucles de rétroaction permettent aux compétences enregistrées d'évoluer ([`packages/agent-continuous-learning`](../packages/agent-continuous-learning))
- Utilisation de l'ordinateur : backend dry-run par défaut, contrôle réel via une jointure MCP ([`packages/agent-computer-use`](../packages/agent-computer-use))
- Une couche de pont qui relie tout ce qui précède à l'orchestrateur de conversation ([`packages/agent-capabilities`](../packages/agent-capabilities))

**Écosystème**
- Un SDK de plugins avec protocole typé ([`packages/plugin-sdk`](../packages/plugin-sdk), [`packages/plugin-protocol`](../packages/plugin-protocol)) et des plugins fournis pour la maison connectée, les médias, les échecs, les agents de codage et le navigateur
- Passerelles de messagerie : Discord, Telegram, Satori, Twitter
- Un service Minecraft et un serveur MCP d'utilisation de l'ordinateur dans [`services/`](../services)
- Une expérience de moteur Godot dans [`engines/`](../engines)

## Pile technique

| | Version |
| --- | --- |
| Node.js | `>=22.0.0` |
| pnpm | `10.33.0` (épinglé via `packageManager`) |
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

Un monorepo pnpm workspace géré avec Turborepo. Les versions des dépendances sont épinglées via les catalogs de [`pnpm-workspace.yaml`](../pnpm-workspace.yaml).

## Démarrage

Nécessite **Node.js ≥ 22** et **pnpm 10.33.0** (`corepack enable` reprend la version épinglée).

```bash
pnpm install
```

`postinstall` compile les paquets du workspace, la première installation est donc longue.

### Exécution

```bash
pnpm dev                  # client web
pnpm dev:tamagotchi       # application de bureau (Electron)
pnpm dev:pocket:android   # mobile, Android
pnpm dev:pocket:ios       # mobile, iOS
pnpm dev:server           # runtime serveur
pnpm dev:docs             # site de documentation
```

### Compilation

```bash
pnpm build                # tous les paquets et applications
pnpm build:web            # client web uniquement
pnpm build:tamagotchi     # application de bureau uniquement
pnpm build:packages       # paquets du workspace uniquement
```

### Vérifications

```bash
pnpm typecheck            # vérification des types sur tout le dépôt
pnpm lint                 # oxlint + eslint via moeru-lint
pnpm test:run             # suites de tests unitaires, visuels et UI
```

## Arborescence

```
apps/         interfaces et leurs backends (web, bureau, mobile, serveur, admin)
packages/     bibliothèques partagées — UI, personnage, mémoire, agent, modèle, audio, outillage
services/     services annexes (parole, MCP d'utilisation de l'ordinateur, passerelles, Minecraft)
plugins/      plugins maison construits sur le SDK de plugins
engines/      expériences de moteurs alternatifs
docs/         site de documentation, documentation produit et notes de recherche
```

## Documentation

- [`ARCHITECTURE.md`](./ARCHITECTURE.md) — comment le système s'articule
- [`FEATURES.md`](./FEATURES.md) — inventaire des fonctionnalités
- [`AGENT_CAPABILITIES.md`](./AGENT_CAPABILITIES.md) — la couche de capacités des agents
- [`COMPUTER_USE_INTEGRATION.md`](./COMPUTER_USE_INTEGRATION.md) — intégration de l'utilisation de l'ordinateur

## Licence

[MIT](../LICENSE).
