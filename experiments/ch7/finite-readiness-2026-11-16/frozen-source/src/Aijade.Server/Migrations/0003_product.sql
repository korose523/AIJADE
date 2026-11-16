-- Product layer, designed for the .NET server: character cards, chats and messages, per-user provider configurations
-- (secrets encrypted at rest), the flux credit ledger, Stripe checkout bookkeeping, the LLM gateway request log and
-- server-side key/value configuration (gateway routes).

CREATE TABLE characters (
  id text PRIMARY KEY,
  owner_id text NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name text NOT NULL,
  description text NOT NULL DEFAULT '',
  persona text NOT NULL DEFAULT '',
  greeting text NOT NULL DEFAULT '',
  model_ref text,
  avatar_ref text,
  tags text[] NOT NULL DEFAULT '{}',
  visibility text NOT NULL DEFAULT 'private' CHECK (visibility IN ('private', 'public')),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz
);
CREATE INDEX characters_owner_idx ON characters (owner_id) WHERE deleted_at IS NULL;

CREATE TABLE chats (
  id text PRIMARY KEY,
  owner_id text NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  character_id text REFERENCES characters(id) ON DELETE SET NULL,
  title text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz
);
CREATE INDEX chats_owner_updated_idx ON chats (owner_id, updated_at DESC) WHERE deleted_at IS NULL;

CREATE TABLE chat_messages (
  id text PRIMARY KEY,
  chat_id text NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
  seq bigserial NOT NULL,
  role text NOT NULL CHECK (role IN ('system', 'user', 'assistant', 'tool')),
  content text NOT NULL,
  meta jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX chat_messages_chat_seq_idx ON chat_messages (chat_id, seq);

CREATE TABLE provider_configs (
  id text PRIMARY KEY,
  owner_id text NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  kind text NOT NULL,
  name text NOT NULL,
  base_url text,
  secret_protected text,
  options jsonb NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX provider_configs_owner_idx ON provider_configs (owner_id);

-- The flux ledger: the balance is a cached sum of the append-only transactions; a request id makes a charge idempotent.
CREATE TABLE flux_accounts (
  user_id text PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  balance bigint NOT NULL DEFAULT 0,
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE flux_transactions (
  id text PRIMARY KEY,
  user_id text NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  amount bigint NOT NULL,
  balance_after bigint NOT NULL,
  kind text NOT NULL CHECK (kind IN ('grant', 'purchase', 'usage', 'refund', 'adjustment')),
  reason text NOT NULL DEFAULT '',
  idempotency_key text UNIQUE,
  meta jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX flux_transactions_user_idx ON flux_transactions (user_id, created_at DESC);

CREATE TABLE stripe_checkouts (
  session_id text PRIMARY KEY,
  user_id text NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  price_id text NOT NULL,
  flux_amount bigint NOT NULL,
  status text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'completed', 'expired')),
  created_at timestamptz NOT NULL DEFAULT now(),
  completed_at timestamptz
);

-- Every webhook event id is processed once.
CREATE TABLE stripe_events (
  id text PRIMARY KEY,
  type text NOT NULL,
  received_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE llm_request_logs (
  id text PRIMARY KEY,
  user_id text NOT NULL,
  model text NOT NULL,
  upstream text NOT NULL,
  status integer NOT NULL,
  prompt_tokens integer,
  completion_tokens integer,
  flux_charged bigint NOT NULL DEFAULT 0,
  duration_ms integer NOT NULL,
  stream boolean NOT NULL DEFAULT false,
  error text,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX llm_request_logs_user_idx ON llm_request_logs (user_id, created_at DESC);

CREATE TABLE config_kv (
  key text PRIMARY KEY,
  value jsonb NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now()
);
