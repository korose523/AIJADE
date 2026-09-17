ALTER TABLE "pgc_states" ADD COLUMN "session_id" text NOT NULL DEFAULT '';
--> statement-breakpoint
ALTER TABLE "pgc_states" ADD COLUMN "trace_id" text NOT NULL DEFAULT '';
--> statement-breakpoint
ALTER TABLE "pgc_states" ADD COLUMN "v6_state" jsonb NOT NULL DEFAULT '{}'::jsonb;
--> statement-breakpoint
ALTER TABLE "memory_versions"
  ADD CONSTRAINT "memory_versions_evidence_pack_id_evidence_packs_id_fk"
  FOREIGN KEY ("evidence_pack_id") REFERENCES "public"."evidence_packs"("id")
  ON DELETE restrict ON UPDATE no action;
--> statement-breakpoint
ALTER TABLE "memory_versions"
  ADD CONSTRAINT "memory_versions_pgc_state_id_pgc_states_id_fk"
  FOREIGN KEY ("pgc_state_id") REFERENCES "public"."pgc_states"("id")
  ON DELETE restrict ON UPDATE no action;
--> statement-breakpoint
ALTER TABLE "evidence_weaves"
  ADD CONSTRAINT "evidence_weaves_tx_id_memory_txs_id_fk"
  FOREIGN KEY ("tx_id") REFERENCES "public"."memory_txs"("id")
  ON DELETE cascade ON UPDATE no action;
