-- v9 / v10 memory-write pipeline (the event bus, the render-trace projection, the causal chain from evidence to memory
-- versions, promotion records and audit). Written for the .NET server from the author's own v9 design; timestamps are
-- timestamptz (UTC) throughout.

CREATE TABLE sessions (
  id text PRIMARY KEY,
  session_ref text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  meta jsonb
);

CREATE TABLE assets (
  id text PRIMARY KEY,
  kind text NOT NULL,
  owner_session_id text REFERENCES sessions(id) ON DELETE CASCADE,
  payload jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

-- The unified event bus. The idempotency key is unique: one key is accepted once (MemoryTx uses its tx id as the key).
CREATE TABLE events (
  id text PRIMARY KEY,
  event_id text NOT NULL,
  trace_id text NOT NULL,
  correlation_id text NOT NULL,
  "timestamp" timestamptz NOT NULL,
  producer text NOT NULL,
  origin_device text NOT NULL,
  privacy_level integer NOT NULL,
  evidence_refs text[] NOT NULL DEFAULT '{}',
  causal_context_refs text[] NOT NULL DEFAULT '{}',
  risk_score real NOT NULL DEFAULT 0,
  topic text NOT NULL,
  payload jsonb,
  idempotency_key text NOT NULL UNIQUE,
  replay_mode text NOT NULL CHECK (replay_mode IN ('live', 'replay')),
  risk_level text NOT NULL CHECK (risk_level IN ('low', 'medium', 'high')),
  tick integer,
  causality jsonb,
  core_state_node text CHECK (core_state_node IS NULL OR core_state_node ~ '^S[0-8]$')
);
CREATE INDEX events_trace_topic_idx ON events (trace_id, topic);
CREATE INDEX events_tick_idx ON events (tick);

-- The render identity projection: one row per trace, built by whichever end (request or receipt) arrives first.
-- Invariants: every row carries at least one end of the identity, and a receipt always carries its content hash.
CREATE TABLE render_traces (
  id text PRIMARY KEY,
  session_id text NOT NULL,
  trace_id text NOT NULL,
  correlation_id text NOT NULL,
  event_id text NOT NULL,
  persona_snapshot_ref text,
  intent_ref text,
  render_ref text,
  applied_params_hash text,
  asset_version_hash text,
  render_ready_event_id text,
  persona_render_requested_event_id text,
  projection_status text NOT NULL DEFAULT 'partial' CHECK (projection_status IN ('partial', 'paired')),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT render_traces_identity_phase_check
    CHECK ((intent_ref IS NOT NULL OR render_ref IS NOT NULL) AND (render_ref IS NULL OR applied_params_hash IS NOT NULL))
);
CREATE INDEX render_traces_trace_id_idx ON render_traces (trace_id);
CREATE INDEX render_traces_intent_ref_idx ON render_traces (intent_ref);
CREATE UNIQUE INDEX render_traces_render_ref_idx ON render_traces (render_ref) WHERE render_ref IS NOT NULL;

CREATE TABLE evidence_packs (
  id text PRIMARY KEY,
  session_id text NOT NULL,
  source text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  note text
);
CREATE INDEX evidence_packs_session_idx ON evidence_packs (session_id);

CREATE TABLE evidence_chunks (
  id text PRIMARY KEY,
  pack_id text NOT NULL REFERENCES evidence_packs(id) ON DELETE CASCADE,
  idx text NOT NULL,
  content text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE beliefs (
  id text PRIMARY KEY,
  proposition text NOT NULL,
  scope text NOT NULL,
  confidence text NOT NULL,
  logit text NOT NULL,
  status text NOT NULL CHECK (status IN ('hypothesis', 'accepted', 'contested', 'retracted')),
  owner text NOT NULL CHECK (owner IN ('user', 'agent', 'world')),
  evidence_ids text[] NOT NULL DEFAULT '{}',
  counter_evidence_ids text[] NOT NULL DEFAULT '{}',
  valid_from timestamptz NOT NULL,
  valid_to timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE pgc_states (
  id text PRIMARY KEY,
  session_id text NOT NULL,
  trace_id text NOT NULL,
  policy_version text NOT NULL,
  components jsonb NOT NULL,
  v6_state jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX pgc_states_session_created_idx ON pgc_states (session_id, created_at DESC);

CREATE TABLE pgc_write_plans (
  id text PRIMARY KEY,
  pgc_state_id text NOT NULL REFERENCES pgc_states(id) ON DELETE CASCADE,
  session_id text NOT NULL,
  trace_id text NOT NULL,
  policy_version text NOT NULL,
  write_plan jsonb NOT NULL,
  contradiction_report jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE memory_txs (
  id text PRIMARY KEY,
  session_id text NOT NULL,
  trace_id text NOT NULL,
  atomicity text NOT NULL CHECK (atomicity IN ('per_write', 'bundle')),
  max_writes text NOT NULL,
  status text NOT NULL CHECK (status IN ('committed', 'rejected', 'partial')),
  created_at timestamptz NOT NULL DEFAULT now()
);

-- A memory version exists only for a committed transaction, always with its content hash and evidence chain.
CREATE TABLE memory_versions (
  id text PRIMARY KEY,
  memory_tx_id text NOT NULL REFERENCES memory_txs(id) ON DELETE CASCADE,
  memory_item_id text NOT NULL,
  memory_write_id text NOT NULL,
  memory_kind text NOT NULL CHECK (memory_kind IN ('long_term', 'persona', 'skill', 'episodic', 'knowledge_card')),
  content_hash_sha256 text NOT NULL,
  evidence_pack_id text NOT NULL REFERENCES evidence_packs(id) ON DELETE RESTRICT,
  evidence_ids text[] NOT NULL,
  pgc_state_id text NOT NULL REFERENCES pgc_states(id) ON DELETE RESTRICT,
  intensity text NOT NULL,
  durability text NOT NULL,
  risk_level text CHECK (risk_level IS NULL OR risk_level IN ('low', 'medium', 'high')),
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE evidence_weaves (
  id text PRIMARY KEY,
  tx_id text NOT NULL REFERENCES memory_txs(id) ON DELETE CASCADE,
  graph_hash text NOT NULL,
  spec jsonb NOT NULL,
  links jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE evolution_specs (
  id text PRIMARY KEY,
  name text NOT NULL,
  spec jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE eval_reports (
  id text PRIMARY KEY,
  name text NOT NULL,
  metric jsonb NOT NULL,
  result jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE audit_log_entries (
  id text PRIMARY KEY,
  tx_id text NOT NULL,
  actor text NOT NULL,
  action text NOT NULL,
  before_hash text,
  after_hash text,
  at timestamptz NOT NULL
);

-- Long-term memory sync across devices, persona snapshots and performance intents, and share notifications.
CREATE TABLE persona_snapshots (
  id text PRIMARY KEY,
  user_id text NOT NULL,
  device_id text NOT NULL,
  privacy_level integer NOT NULL CHECK (privacy_level BETWEEN 0 AND 3),
  persona jsonb NOT NULL,
  version integer NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE performance_intents (
  id text PRIMARY KEY,
  user_id text NOT NULL,
  device_id text NOT NULL,
  persona_snapshot_ref text NOT NULL,
  privacy_level integer NOT NULL CHECK (privacy_level BETWEEN 0 AND 3),
  intent jsonb NOT NULL,
  time_marked timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE memory_sync_outbox (
  id text PRIMARY KEY,
  user_id text NOT NULL,
  source_device_id text NOT NULL,
  entity_type text NOT NULL,
  entity_id text NOT NULL,
  privacy_level integer NOT NULL CHECK (privacy_level BETWEEN 0 AND 3),
  payload jsonb NOT NULL,
  status text NOT NULL DEFAULT 'pending',
  created_at timestamptz NOT NULL DEFAULT now(),
  processed_at timestamptz
);

CREATE TABLE sharing_notifications (
  id text PRIMARY KEY,
  user_id text NOT NULL,
  candidate_id text NOT NULL,
  channel text NOT NULL,
  content_ref text NOT NULL,
  score real NOT NULL,
  privacy_level integer NOT NULL CHECK (privacy_level BETWEEN 0 AND 3),
  status text NOT NULL DEFAULT 'pending',
  created_at timestamptz NOT NULL DEFAULT now(),
  delivered_at timestamptz
);

-- First-party product analytics: user id stays in the database, never in metric labels.
CREATE TABLE product_events (
  id text PRIMARY KEY,
  user_id text NOT NULL,
  feature text NOT NULL,
  action text NOT NULL,
  status text NOT NULL,
  source text,
  model text,
  provider text,
  reason text,
  metadata jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX product_events_feature_action_created_at_idx ON product_events (feature, action, created_at);
CREATE INDEX product_events_user_id_created_at_idx ON product_events (user_id, created_at);
CREATE INDEX product_events_created_at_idx ON product_events (created_at);
