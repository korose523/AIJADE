-- Multi-user ownership of v9 memory sessions. The original companion was single-user; on a shared server every memory
-- session belongs to the account that first wrote perception into it, and only that account may read or forget it.
CREATE TABLE memory_session_owners (
  session_id text PRIMARY KEY,
  user_id text NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX memory_session_owners_user_idx ON memory_session_owners (user_id);
