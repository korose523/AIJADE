/**
 * Amber HE Hologram Mode
 *
 * 适配 Gowild 琥珀 HE 全息投影硬件 (1280x720 全息屏)
 * 启用方式: .env 中设置 HOLOGRAM_MODE=true 或在 URL 添加 ?hologram=1
 */

/** 检测是否启用全息模式 */
export function isHologramMode(): boolean {
  if (typeof window === 'undefined')
    return false
  const params = new URLSearchParams(window.location.search)
  return params.get('hologram') === '1' || params.get('amber') === '1'
}

/** 琥珀 HE 全息 CSS 类名 */
export const HOLOGRAM_CLASS = 'amber-he-hologram'

/** 应用全息样式到 document */
export function applyHologramStyles() {
  if (!isHologramMode())
    return

  const style = document.createElement('style')
  style.id = 'amber-he-hologram-style'
  style.textContent = `
    /* Amber HE 全息模式样式 */
    body.${HOLOGRAM_CLASS} {
      background: transparent !important;
      overflow: hidden;
    }
    
    .${HOLOGRAM_CLASS} .stage-scene {
      /* 全息投影: 深色背景 + 投影效果 */
      background: radial-gradient(ellipse at center, rgba(0,0,0,0.3) 0%, transparent 70%);
    }
    
    .${HOLOGRAM_CLASS} .vrm-model {
      /* VRM 模型缩放适配 720p */
      transform: scale(0.85);
      filter: brightness(1.2) contrast(1.1);
    }
    
    .${HOLOGRAM_CLASS} .chat-panel {
      /* 聊天面板半透明浮层 */
      background: rgba(0,0,0,0.4) !important;
      backdrop-filter: blur(10px);
      max-height: 40vh;
    }
    
    /* 智能音箱模式指示器 */
    .smart-speaker-indicator {
      position: fixed;
      bottom: 20px;
      left: 50%;
      transform: translateX(-50%);
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 8px 16px;
      border-radius: 20px;
      background: rgba(0,0,0,0.5);
      color: #fff;
      font-size: 14px;
      backdrop-filter: blur(10px);
      transition: opacity 0.3s;
      z-index: 1000;
    }
    
    .smart-speaker-indicator .dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: #4ade80;
      animation: pulse-dot 2s infinite;
    }
    
    .smart-speaker-indicator.listening .dot {
      background: #60a5fa;
      animation: pulse-dot 0.6s infinite;
    }
    
    .smart-speaker-indicator.speaking .dot {
      background: #f59e0b;
    }
    
    @keyframes pulse-dot {
      0%, 100% { opacity: 1; transform: scale(1); }
      50% { opacity: 0.5; transform: scale(0.7); }
    }
  `
  document.head.appendChild(style)
  document.body.classList.add(HOLOGRAM_CLASS)

  console.log('[AmberHE] 全息模式已启用')
}
