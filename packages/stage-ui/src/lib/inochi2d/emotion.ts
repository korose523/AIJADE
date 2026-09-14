/**
 * 情绪 → Inochi2D 参数映射（MVP 适配器雏形）。
 *
 * AIJADE 的 `Emotion` 枚举运动名（见 `packages/stage-ui-live2d/src/constants/emotions.ts`）：
 *   Happy / Sad / Angry / Think / Surprise / Awkward / Question / Idle / Curious
 * （`Neutral` 映射到 `Idle`）。
 *
 * Inochi2D 用自有参数名（惯例：MouthOpen / MouthSmile / EyeOpen / EyeSmile / Brow / BrowAngle /
 * HeadX / HeadY / BodyAngleX / Breath / Tear / Blush 等）。
 *
 * ⚠️ TODO：下列映射是**按惯例的占位**，真实参数名/取值区间以你用 Inochi Creator 导出的 `.inp` 为准。
 * 等拿到真实模型后，对照其 `parameters[].name` 校准此处。
 */

/** AIJADE 情绪名 → Inochi2D 参数目标值（0..1，超出范围按模型实际约束裁剪） */
export const EMOTION_TO_INOCHI2D: Record<string, Record<string, number>> = {
  Idle: {
    Breath: 0.1,
    HeadY: 0.5,
  },
  Happy: {
    MouthSmile: 1,
    EyeSmile: 1,
    Blush: 0.6,
  },
  Sad: {
    Brow: -0.4,
    MouthSmile: -0.3,
    Tear: 0.25,
  },
  Angry: {
    Brow: 0.4,
    MouthOpen: 0.2,
  },
  Think: {
    Brow: 0.2,
    HeadX: -0.1,
  },
  Surprise: {
    EyeOpen: 1,
    MouthOpen: 1,
    Brow: 0.6,
  },
  Awkward: {
    EyeSmile: 0.4,
    MouthSmile: 0.2,
  },
  Question: {
    HeadX: 0.15,
    Brow: 0.1,
  },
  Curious: {
    EyeOpen: 0.6,
    HeadX: 0.2,
    MouthSmile: 0.3,
  },
}

/** 取某情绪对应的 Inochi2D 参数目标值；未知情绪回退 Idle */
export function emotionToInochi2DParams(emotion: string): Record<string, number> {
  return EMOTION_TO_INOCHI2D[emotion] ?? EMOTION_TO_INOCHI2D.Idle
}
