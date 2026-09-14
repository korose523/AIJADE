# AIJADE 远程访问 + Android APK 部署指南

## 一、虚拟局域网 (Tailscale) 远程访问

### 已安装
- Tailscale v1.98.4 已安装
- 需要登录: `tailscale up` (首次需要浏览器认证)

### 设置步骤
```bash
# 1. 登录 Tailscale
tailscale up --accept-routes

# 2. 浏览器打开认证链接 → 登录 GitHub/Google 账号

# 3. 获取 AIJADE 的 Tailscale IP
tailscale ip -4
# 例如: 100.95.34.82

# 4. 在其他设备安装 Tailscale 并登录同一账号
# 手机: 下载 Tailscale App
# 其他电脑: https://tailscale.com/download

# 5. 远程设备访问 AIJADE
# 浏览器打开: http://100.95.34.82:5173
# 琥珀 HE: http://100.95.34.82:5173/?hologram=1
```

### 原理
```
手机 (外网) ──Tailscale──→ 你的电脑 (AIJADE:5173)
      ↑                          ↑
  100.x.x.x                100.95.34.82
  (Tailscale IP)           (Tailscale IP)

所有流量通过 Tailscale WireGuard 加密隧道传输
```

### 备选方案 (无需安装客户端)

#### ngrok (公网穿透)
```bash
ngrok http 5173
# 获得公网 URL: https://xxx.ngrok.io → 任何人都能访问
```

#### Cloudflare Tunnel
```bash
cloudflared tunnel --url http://localhost:5173
# 获得: https://xxx.trycloudflare.com
```

---

## 二、Android APK 构建

### 一键构建
```bash
cd H:\AIJADE
build_apk.bat
```

### 手动构建
```bash
# 环境
set JAVA_HOME=C:\Program Files\Android\Android Studio\jbr
set ANDROID_HOME=%LOCALAPPDATA%\Android\Sdk

# 构建
cd H:\AIJADE\apps\stage-pocket
pnpm build                    # Vite 构建
pnpm exec cap sync android    # 同步到 Android
cd android && gradlew assembleDebug  # 打包 APK

# 输出
# app/build/outputs/apk/debug/app-debug.apk
```

### 安装到手机
```bash
adb install app-debug.apk
# 或直接传 APK 到手机安装
```

### AIJADE APK 首次配置
1. 打开 AIJADE App
2. 设置 → 服务器地址 → 输入 `http://你的Tailscale IP:5173`
3. 配置 LLM Provider → Ollama 或 OpenAI Compatible
4. 开始对话

---

## 三、安全提醒

| 级别 | 方案 | 适用场景 |
|------|------|----------|
| 家庭内网 | WiFi 直连 | 同一 WiFi 下 |
| 个人远程 | **Tailscale** (推荐) | 个人设备间安全连接 |
| 公开演示 | ngrok / Cloudflare | 临时分享给他人 |
