-- What the user is looking at right now, as reported by their browser extension (latest per source, per account).
-- Short-lived context for the companion, not memory: only the newest report is kept and old ones stop being offered.
CREATE TABLE live_context (
  user_id text NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  source text NOT NULL,
  payload jsonb NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, source)
);
