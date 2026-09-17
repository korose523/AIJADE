ALTER TABLE "events"
  ALTER COLUMN "privacy_level" DROP DEFAULT,
  ALTER COLUMN "risk_score" DROP DEFAULT,
  ALTER COLUMN "privacy_level" TYPE integer USING "privacy_level"::integer,
  ALTER COLUMN "risk_score" TYPE real USING "risk_score"::real,
  ALTER COLUMN "privacy_level" SET DEFAULT 1,
  ALTER COLUMN "risk_score" SET DEFAULT 0;
