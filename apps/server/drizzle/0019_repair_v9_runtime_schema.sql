ALTER TABLE "pgc_states"
  ADD COLUMN IF NOT EXISTS "session_id" text NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS "trace_id" text NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS "v6_state" jsonb NOT NULL DEFAULT '{}'::jsonb;
--> statement-breakpoint
ALTER TABLE "events"
  ADD COLUMN IF NOT EXISTS "origin_device" text NOT NULL DEFAULT 'legacy',
  ADD COLUMN IF NOT EXISTS "privacy_level" integer NOT NULL DEFAULT 1,
  ADD COLUMN IF NOT EXISTS "evidence_refs" text[] NOT NULL DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS "causal_context_refs" text[] NOT NULL DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS "risk_score" real NOT NULL DEFAULT 0;
