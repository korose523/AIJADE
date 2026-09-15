CREATE TABLE "assets" (
	"id" text PRIMARY KEY NOT NULL,
	"kind" text NOT NULL,
	"owner_session_id" text,
	"payload" jsonb NOT NULL,
	"created_at" timestamp DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "audit_log_entries" (
	"id" text PRIMARY KEY NOT NULL,
	"tx_id" text NOT NULL,
	"actor" text NOT NULL,
	"action" text NOT NULL,
	"before_hash" text,
	"after_hash" text,
	"at" timestamp NOT NULL
);
--> statement-breakpoint
CREATE TABLE "beliefs" (
	"id" text PRIMARY KEY NOT NULL,
	"proposition" text NOT NULL,
	"scope" text NOT NULL,
	"confidence" text NOT NULL,
	"logit" text NOT NULL,
	"status" text NOT NULL,
	"owner" text NOT NULL,
	"evidence_ids" text[] DEFAULT '{}' NOT NULL,
	"counter_evidence_ids" text[] DEFAULT '{}' NOT NULL,
	"valid_from" timestamp NOT NULL,
	"valid_to" timestamp,
	"created_at" timestamp DEFAULT now() NOT NULL,
	"updated_at" timestamp DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "eval_reports" (
	"id" text PRIMARY KEY NOT NULL,
	"name" text NOT NULL,
	"metric" jsonb NOT NULL,
	"result" jsonb NOT NULL,
	"created_at" timestamp DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "events" (
	"id" text PRIMARY KEY NOT NULL,
	"event_id" text NOT NULL,
	"trace_id" text NOT NULL,
	"correlation_id" text NOT NULL,
	"timestamp" timestamp NOT NULL,
	"producer" text NOT NULL,
	"topic" text NOT NULL,
	"payload" jsonb,
	"idempotency_key" text NOT NULL,
	"replay_mode" text NOT NULL,
	"risk_level" text NOT NULL,
	CONSTRAINT "events_idempotency_key_unique" UNIQUE("idempotency_key")
);
--> statement-breakpoint
CREATE TABLE "evidence_chunks" (
	"id" text PRIMARY KEY NOT NULL,
	"pack_id" text NOT NULL,
	"idx" text NOT NULL,
	"content" text NOT NULL,
	"created_at" timestamp DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "evidence_packs" (
	"id" text PRIMARY KEY NOT NULL,
	"session_id" text NOT NULL,
	"source" text NOT NULL,
	"created_at" timestamp DEFAULT now() NOT NULL,
	"note" text
);
--> statement-breakpoint
CREATE TABLE "evidence_weaves" (
	"id" text PRIMARY KEY NOT NULL,
	"tx_id" text NOT NULL,
	"graph_hash" text NOT NULL,
	"spec" jsonb NOT NULL,
	"links" jsonb NOT NULL,
	"created_at" timestamp DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "evolution_specs" (
	"id" text PRIMARY KEY NOT NULL,
	"name" text NOT NULL,
	"spec" jsonb NOT NULL,
	"created_at" timestamp DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "memory_txs" (
	"id" text PRIMARY KEY NOT NULL,
	"session_id" text NOT NULL,
	"trace_id" text NOT NULL,
	"atomicity" text NOT NULL,
	"max_writes" text NOT NULL,
	"status" text NOT NULL,
	"created_at" timestamp DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "memory_versions" (
	"id" text PRIMARY KEY NOT NULL,
	"memory_tx_id" text NOT NULL,
	"memory_item_id" text NOT NULL,
	"memory_write_id" text NOT NULL,
	"memory_kind" text NOT NULL,
	"content_hash_sha256" text NOT NULL,
	"evidence_pack_id" text NOT NULL,
	"evidence_ids" text[] NOT NULL,
	"pgc_state_id" text NOT NULL,
	"intensity" text NOT NULL,
	"durability" text NOT NULL,
	"risk_level" text,
	"created_at" timestamp DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "pgc_states" (
	"id" text PRIMARY KEY NOT NULL,
	"policy_version" text NOT NULL,
	"components" jsonb NOT NULL,
	"created_at" timestamp DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "pgc_write_plans" (
	"id" text PRIMARY KEY NOT NULL,
	"pgc_state_id" text NOT NULL,
	"session_id" text NOT NULL,
	"trace_id" text NOT NULL,
	"policy_version" text NOT NULL,
	"write_plan" jsonb NOT NULL,
	"contradiction_report" jsonb NOT NULL,
	"created_at" timestamp DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "sessions" (
	"id" text PRIMARY KEY NOT NULL,
	"session_ref" text NOT NULL,
	"created_at" timestamp DEFAULT now() NOT NULL,
	"updated_at" timestamp DEFAULT now() NOT NULL,
	"meta" jsonb
);
--> statement-breakpoint
ALTER TABLE "assets" ADD CONSTRAINT "assets_owner_session_id_sessions_id_fk" FOREIGN KEY ("owner_session_id") REFERENCES "public"."sessions"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "evidence_chunks" ADD CONSTRAINT "evidence_chunks_pack_id_evidence_packs_id_fk" FOREIGN KEY ("pack_id") REFERENCES "public"."evidence_packs"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "memory_versions" ADD CONSTRAINT "memory_versions_memory_tx_id_memory_txs_id_fk" FOREIGN KEY ("memory_tx_id") REFERENCES "public"."memory_txs"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "pgc_write_plans" ADD CONSTRAINT "pgc_write_plans_pgc_state_id_pgc_states_id_fk" FOREIGN KEY ("pgc_state_id") REFERENCES "public"."pgc_states"("id") ON DELETE cascade ON UPDATE no action;