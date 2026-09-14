# AIJADE on Gowild Amber HE (holoera) — Quick Deploy

## Hardware Specs
| Component | Spec | AIJADE Adapt |
|-----------|------|-----------|
| Display | 1280×720 holographic 16:9 | Transparent bg + dark theme |
| Camera | Front 5MP | Face detection → wake AIJADE |
| Mic | Array mic | AIJADE STT |
| Speaker | Stereo 2×3W | AIJADE TTS output |
| OS | Android 5.1+ | PWA / Capacitor APK |
| WiFi | 802.11 b/g/n | WebSocket to AIJADE Server |

## Deploy (PWA — Recommended)
1. Start AIJADE Server: `pnpm dev` on your PC
2. On Amber HE browser, open: `http://YOUR-PC-IP:5173`
3. Add to Home Screen

## Deploy (APK)
1. Build: `pnpm -F @proj-aijade/stage-pocket build`
2. Sync: `npx cap sync android`
3. Build APK: `cd apps/stage-pocket/android && ./gradlew assembleDebug`
4. Install: `adb install app-debug.apk`

## Hologram CSS
```css
body { background: transparent !important; }
.vrm-container { transform: scale(1.5); filter: brightness(1.3) contrast(1.2) drop-shadow(0 0 20px rgba(100,200,255,0.3)); }
```
