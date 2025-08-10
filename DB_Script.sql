

DROP TABLE event_payment;

CREATE TABLE event_payment (
  id SERIAL PRIMARY KEY,

  transaction_id TEXT UNIQUE NOT NULL,
  username       TEXT NOT NULL,
  email          TEXT NOT NULL,
  phone          TEXT NOT NULL,
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

  created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  last_updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Helpful indexes
CREATE INDEX IF NOT EXISTS idx_event_payment_txn      ON event_payment (transaction_id);
CREATE INDEX IF NOT EXISTS idx_event_payment_qrfile   ON event_payment (qr_code_filename);
CREATE INDEX IF NOT EXISTS idx_event_payment_qr_sent  ON event_payment (qr_sent);
CREATE INDEX IF NOT EXISTS idx_event_payment_reissued ON event_payment (qr_reissued_yn);
CREATE INDEX IF NOT EXISTS idx_event_payment_checked  ON event_payment (all_attendees_checked_in);
