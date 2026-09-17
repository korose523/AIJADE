CREATE TABLE IF NOT EXISTS "persona_snapshots" (
  "id" text PRIMARY KEY NOT NULL,
  "user_id" text NOT NULL,
  "device_id" text NOT NULL,
  "privacy_level" integer NOT NULL,
  "persona" jsonb NOT NULL,
  "version" integer NOT NULL,
  "created_at" timestamp DEFAULT now() NOT NULL
);
CREATE TABLE IF NOT EXISTS "performance_intents" (
  "id" text PRIMARY KEY NOT NULL,
  "user_id" text NOT NULL,
  "device_id" text NOT NULL,
  "persona_snapshot_ref" text NOT NULL,
  "privacy_level" integer NOT NULL,
  "intent" jsonb NOT NULL,
  "time_marked" timestamp NOT NULL,
  "created_at" timestamp DEFAULT now() NOT NULL
);
CREATE TABLE IF NOT EXISTS "memory_sync_outbox" (
  "id" text PRIMARY KEY NOT NULL,
  "user_id" text NOT NULL,
  "source_device_id" text NOT NULL,
  "entity_type" text NOT NULL,
  "entity_id" text NOT NULL,
  "privacy_level" integer NOT NULL,
  "payload" jsonb NOT NULL,
  "status" text DEFAULT 'pending' NOT NULL,
  "created_at" timestamp DEFAULT now() NOT NULL,
  "processed_at" timestamp
);
CREATE TABLE IF NOT EXISTS "sharing_notifications" (
  "id" text PRIMARY KEY NOT NULL,
  "user_id" text NOT NULL,
  "candidate_id" text NOT NULL,
  "channel" text NOT NULL,
  "content_ref" text NOT NULL,
  "score" real NOT NULL,
  "privacy_level" integer NOT NULL,
  "status" text DEFAULT 'pending' NOT NULL,
  "created_at" timestamp DEFAULT now() NOT NULL,
  "delivered_at" timestamp
);
CREATE INDEX IF NOT EXISTS "memory_sync_outbox_user_status_idx"
  ON "memory_sync_outbox" ("user_id", "status");
CREATE INDEX IF NOT EXISTS "sharing_notifications_user_idx"
  ON "sharing_notifications" ("user_id", "created_at");
