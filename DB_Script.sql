

DROP TABLE event_payment;

CREATE TABLE event_payment (
  id SERIAL PRIMARY KEY,

  transaction_id TEXT UNIQUE NOT NULL,
  username       TEXT NOT NULL,
  email          TEXT NOT NULL,
  phone          TEXT ,
  address        TEXT,

  membership_paid     BOOLEAN DEFAULT FALSE,
  early_bird_applied  BOOLEAN DEFAULT FALSE,
  payment_date        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  amount              NUMERIC(10,2) NOT NULL,
  paid_for            TEXT NOT NULL,
  remarks             TEXT,

  qr_generated    BOOLEAN DEFAULT FALSE,
  qr_generated_at TIMESTAMP,

  qr_sent    BOOLEAN DEFAULT FALSE,
  qr_sent_at TIMESTAMP,

  qr_code_filename TEXT,
  qr_s3_url        TEXT,

  -- Verifier-facing counts
  number_of_attendees INTEGER DEFAULT 1 CHECK (number_of_attendees >= 0),
  number_checked_in   INTEGER DEFAULT 0 CHECK (number_checked_in   >= 0),

  -- Status flag for verifier (read-only, computed)
  all_attendees_checked_in BOOLEAN
    GENERATED ALWAYS AS (
      (number_of_attendees > 0) AND (number_checked_in >= number_of_attendees)
    ) STORED,

  -- Optional operational fields for on-site verification
  last_checked_in_at TIMESTAMP,
  last_checked_in_by TEXT,         -- username/email of verifier device/operator
  revoked_yn         BOOLEAN DEFAULT FALSE,  -- admin can revoke access if needed
  verifier_notes     TEXT,

  qr_reissued_yn BOOLEAN DEFAULT FALSE,
  qr_reissued_at TIMESTAMP,

  created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  last_updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

truncate TABLE event_payment;


-- Helpful indexes
-- 1) Pending rows (boolean is low-selectivity; use a partial)
CREATE INDEX IF NOT EXISTS event_payment_qr_generated_false
  ON event_payment (payment_date DESC)
  WHERE qr_generated = FALSE;
-- Note: include the common ORDER BY column in the index to avoid extra sort work.
-- If you order by last_updated_at instead, index that column.

-- 2) Unsent emails (if you have a sender job)
CREATE INDEX IF NOT EXISTS event_payment_qr_sent_false
  ON event_payment (last_updated_at DESC)
  WHERE qr_sent = FALSE;

-- 3) Reissued-only views (if you use them)
CREATE INDEX IF NOT EXISTS event_payment_reissued_true
  ON event_payment (last_updated_at DESC)
  WHERE qr_reissued_yn = TRUE;

-- 4) Fully checked-in views (if used)
CREATE INDEX IF NOT EXISTS event_payment_all_checked_true
  ON event_payment (last_checked_in_at DESC)
  WHERE all_attendees_checked_in = TRUE;

-- 5) Filename lookups (only if you actually query by file name)
CREATE INDEX IF NOT EXISTS event_payment_qrfile_not_empty
  ON event_payment (qr_code_filename)
  WHERE qr_code_filename IS NOT NULL AND qr_code_filename <> '';

-- 6) If you move name/email search into SQL, enable trigram and index:
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE INDEX IF NOT EXISTS event_payment_username_trgm
  ON event_payment USING gin (lower(username) gin_trgm_ops);

CREATE INDEX IF NOT EXISTS event_payment_email_trgm
  ON event_payment USING gin (lower(email) gin_trgm_ops);

-- Optional: time filters
CREATE INDEX IF NOT EXISTS event_payment_payment_date
  ON event_payment (payment_date);

CREATE INDEX IF NOT EXISTS event_payment_last_updated_at
  ON event_payment (last_updated_at);


SELECT column_name, is_generated, is_identity, column_default
FROM information_schema.columns
WHERE table_name = 'event_payment'
ORDER BY ordinal_position;

