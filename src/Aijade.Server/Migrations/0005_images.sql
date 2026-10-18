-- Images the companion drew ("artistry"), kept per owner and served only to that owner. Deleted with the account.
CREATE TABLE generated_images (
  id text PRIMARY KEY,
  owner_id text NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  prompt text NOT NULL,
  mime text NOT NULL,
  bytes bytea NOT NULL,
  provider text NOT NULL,
  model text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX generated_images_owner_idx ON generated_images (owner_id, created_at DESC);
