-- v10 §6.2 / 报告 P1-2：render_traces 投影补全（缺配检测状态位 + 两端事件 id）
-- 两个事件 id 列可为空：投影行可能先由 `persona.render_requested` 或 `lpm.render_ready`
-- 单独建立，另一端稍后补齐（详见 services/domain/v9-events.ts 的 upsertRenderTraceProjection）。
-- `projection_status` 为 NOT NULL：存量行以 DEFAULT 'partial' 落地（旧数据视为未配对补全），
-- 新行由投影写入逻辑显式计算（paired / partial）。

ALTER TABLE "render_traces" ADD COLUMN "render_ready_event_id" text;
--> statement-breakpoint
ALTER TABLE "render_traces" ADD COLUMN "persona_render_requested_event_id" text;
--> statement-breakpoint
ALTER TABLE "render_traces" ADD COLUMN "projection_status" text NOT NULL DEFAULT 'partial';
