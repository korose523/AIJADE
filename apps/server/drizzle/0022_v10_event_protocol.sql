ALTER TABLE "events" ADD COLUMN IF NOT EXISTS "tick" integer;
--> statement-breakpoint
ALTER TABLE "events" ADD COLUMN IF NOT EXISTS "causality" jsonb;
