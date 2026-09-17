ALTER TABLE "events" ADD COLUMN IF NOT EXISTS "core_state_node" text;
--> statement-breakpoint
CREATE INDEX IF NOT EXISTS "events_tick_input_hash_idx" ON "events" ("tick", ("causality" ->> 'inputHash'));
