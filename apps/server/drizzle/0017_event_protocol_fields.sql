ALTER TABLE "events" ADD COLUMN "origin_device" text NOT NULL DEFAULT 'legacy';
--> statement-breakpoint
ALTER TABLE "events" ADD COLUMN "privacy_level" text NOT NULL DEFAULT '1';
--> statement-breakpoint
ALTER TABLE "events" ADD COLUMN "evidence_refs" text[] NOT NULL DEFAULT '{}';
--> statement-breakpoint
ALTER TABLE "events" ADD COLUMN "causal_context_refs" text[] NOT NULL DEFAULT '{}';
--> statement-breakpoint
ALTER TABLE "events" ADD COLUMN "risk_score" text NOT NULL DEFAULT '0';
