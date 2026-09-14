# @proj-aijade/electron-vueuse

VueUse-like composables and helpers shared across AIJADE Electron apps.

## What it provides

- Renderer composables for common Electron behaviors (`mouse`, `window bounds`, `auto updater`, etc.)
- A reusable Eventa context/invoke pattern (`useElectronEventaContext`, `useElectronEventaInvoke`)
- Eventa context/invoke ergonomics for renderer code
- Main-process loop utilities (`useLoop`, `createRendererLoop`)

For IPC contract definitions, use `@proj-aijade/electron-eventa`.

## Usage

```ts
import { electron } from '@proj-aijade/electron-eventa'
import { useElectronEventaInvoke } from '@proj-aijade/electron-vueuse'

const openSettings = useElectronEventaInvoke(electron.window.getBounds)
```

```ts
import { createRendererLoop } from '@proj-aijade/electron-vueuse/main'
```
