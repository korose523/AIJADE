-- Accounts: users, password credentials, opaque bearer sessions (only the SHA-256 of a token is stored) and external
-- identities (OIDC). Designed for the .NET server.

CREATE TABLE users (
  id text PRIMARY KEY,
  email text NOT NULL,
  name text NOT NULL DEFAULT '',
  role text NOT NULL DEFAULT 'user' CHECK (role IN ('user', 'admin')),
  email_verified boolean NOT NULL DEFAULT false,
  banned boolean NOT NULL DEFAULT false,
  ban_reason text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz
);
CREATE UNIQUE INDEX users_email_idx ON users (lower(email)) WHERE deleted_at IS NULL;

CREATE TABLE user_passwords (
  user_id text PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  hash text NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE auth_sessions (
  token_hash text PRIMARY KEY,
  user_id text NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz NOT NULL,
  user_agent text,
  ip text
);
CREATE INDEX auth_sessions_user_idx ON auth_sessions (user_id);

CREATE TABLE user_identities (
  provider text NOT NULL,
  subject text NOT NULL,
  user_id text NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (provider, subject)
);
