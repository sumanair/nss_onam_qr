-- most indexes, triggers not impl.

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

truncate TABLE event_payment cascade;



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


truncate table event_checkin;

CREATE TABLE event_checkin (
  id BIGSERIAL PRIMARY KEY,
  payment_id BIGINT NOT NULL REFERENCES event_payment(id) ON DELETE CASCADE,

  -- How many people were checked in this batch (e.g., 2 now, 3 later)
  count_checked_in INTEGER NOT NULL CHECK (count_checked_in > 0),

  -- Operational / audit fields
  verifier_id   TEXT,          -- who performed the check-in (username/email/device)
  device_id     TEXT,          -- optional device fingerprint
  location_note TEXT,          -- optional (gate name, counter, etc.)
  notes         TEXT,

  -- Revocation support (undo a mistaken batch without deleting history)
  revoked_yn  BOOLEAN  DEFAULT FALSE,
  revoked_at  TIMESTAMP,
  revoked_by  TEXT,

  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Fast lookups and rollups
CREATE INDEX IF NOT EXISTS event_checkin_payment_idx
  ON event_checkin (payment_id, created_at DESC);

-- Only active (non-revoked) batches for common queries
CREATE INDEX IF NOT EXISTS event_checkin_payment_active_idx
  ON event_checkin (payment_id)
  WHERE revoked_yn = FALSE;


CREATE OR REPLACE FUNCTION enforce_remaining_capacity()
RETURNS TRIGGER AS $$
DECLARE
  planned   INTEGER;
  checked   INTEGER;
  adding    INTEGER := NEW.count_checked_in;
BEGIN
  -- Treat revoked rows as 0; NEW is not yet revoked
  SELECT ep.number_of_attendees
       , COALESCE(SUM(CASE WHEN ec.revoked_yn IS FALSE THEN ec.count_checked_in ELSE 0 END), 0)
    INTO planned, checked
  FROM event_payment ep
  LEFT JOIN event_checkin ec ON ec.payment_id = ep.id
  WHERE ep.id = NEW.payment_id
  GROUP BY ep.number_of_attendees;

  IF planned IS NULL THEN
    RAISE EXCEPTION 'Unknown payment_id %', NEW.payment_id;
  END IF;

  IF (checked + adding) > planned THEN
    RAISE EXCEPTION 'Check-in exceeds remaining capacity: planned %, already %, adding %',
      planned, checked, adding;
  END IF;

  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_enforce_remaining_capacity ON event_checkin;
CREATE TRIGGER trg_enforce_remaining_capacity
BEFORE INSERT ON event_checkin
FOR EACH ROW
EXECUTE FUNCTION enforce_remaining_capacity();




CREATE OR REPLACE FUNCTION stamp_parent_on_checkin()
RETURNS TRIGGER AS $$
BEGIN
  UPDATE event_payment
     SET last_checked_in_at = CURRENT_TIMESTAMP,
         last_checked_in_by = COALESCE(NEW.verifier_id, last_checked_in_by),
         last_updated_at    = CURRENT_TIMESTAMP
   WHERE id = NEW.payment_id;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_stamp_parent_on_checkin ON event_checkin;
CREATE TRIGGER trg_stamp_parent_on_checkin
AFTER INSERT ON event_checkin
FOR EACH ROW
EXECUTE FUNCTION stamp_parent_on_checkin();


CREATE OR REPLACE VIEW v_event_payment_rollup AS
SELECT
  ep.*,
  COALESCE(SUM(CASE WHEN ec.revoked_yn = FALSE THEN ec.count_checked_in END), 0)    AS checked_in_count,
  GREATEST(ep.number_of_attendees
           - COALESCE(SUM(CASE WHEN ec.revoked_yn = FALSE THEN ec.count_checked_in END), 0), 0) AS remaining_count,
  (ep.number_of_attendees > 0 AND
   COALESCE(SUM(CASE WHEN ec.revoked_yn = FALSE THEN ec.count_checked_in END), 0) >= ep.number_of_attendees) AS all_attendees_checked_in_derived
FROM event_payment ep
LEFT JOIN event_checkin ec ON ec.payment_id = ep.id
GROUP BY ep.id;



SELECT count(*) FROM event_payment
SELECT count(*) FROM  event_checkin
