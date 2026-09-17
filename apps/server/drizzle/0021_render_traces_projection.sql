CREATE TABLE IF NOT EXISTS "render_traces" (
  "id" text PRIMARY KEY NOT NULL,
  "session_id" text NOT NULL,
  "trace_id" text NOT NULL,
  "correlation_id" text NOT NULL,
  "event_id" text NOT NULL,
  "persona_snapshot_ref" text,
  "intent_ref" text,
  "render_ref" text,
  "applied_params_hash" text,
  "asset_version_hash" text,
  "created_at" timestamp DEFAULT now() NOT NULL,
  "updated_at" timestamp DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE INDEX IF NOT EXISTS "render_traces_trace_id_idx" ON "render_traces" ("trace_id");
--> statement-breakpoint
CREATE INDEX IF NOT EXISTS "render_traces_intent_ref_idx" ON "render_traces" ("intent_ref");
--> statement-breakpoint
CREATE UNIQUE INDEX IF NOT EXISTS "render_traces_render_ref_idx"
  ON "render_traces" ("render_ref")
  WHERE "render_ref" IS NOT NULL;
