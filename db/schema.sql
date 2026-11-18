-- MemberDesk CRM - SQLite schema
-- Applied automatically on first run (see crm/sql_store.py).
-- Text columns default to '' so "not provided" is always an empty string, never NULL.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS members (
    member_id           TEXT PRIMARY KEY CHECK (member_id GLOB '[0-9]*' AND length(member_id) BETWEEN 3 AND 10),
    name                TEXT NOT NULL,
    gender              TEXT NOT NULL DEFAULT '',
    dob                 TEXT NOT NULL DEFAULT '',          -- YYYY-MM-DD
    marital_status      TEXT NOT NULL DEFAULT '',
    mobile              TEXT NOT NULL DEFAULT '',
    alt_mobile          TEXT NOT NULL DEFAULT '',
    email               TEXT NOT NULL DEFAULT '',
    member_status       TEXT NOT NULL DEFAULT '',          -- e.g. Qualified, Student
    category            TEXT NOT NULL DEFAULT '',          -- e.g. Fellow, Associate
    practicing          TEXT NOT NULL DEFAULT '',
    position            TEXT NOT NULL DEFAULT '',          -- office-bearer role
    ob_ecm              TEXT NOT NULL DEFAULT '',
    place               TEXT NOT NULL DEFAULT '',
    state               TEXT NOT NULL DEFAULT '',
    chapter             TEXT NOT NULL DEFAULT '',
    address             TEXT NOT NULL DEFAULT '',
    pincode             TEXT NOT NULL DEFAULT '',
    education           TEXT NOT NULL DEFAULT '',
    specialization      TEXT NOT NULL DEFAULT '',
    gstp_no             TEXT NOT NULL DEFAULT '',
    itp_no              TEXT NOT NULL DEFAULT '',
    advocate_others     TEXT NOT NULL DEFAULT '',
    organization        TEXT NOT NULL DEFAULT '',
    subscription        INTEGER NOT NULL DEFAULT 0 CHECK (subscription >= 0),
    payment_date        TEXT NOT NULL DEFAULT '',          -- YYYY-MM-DD
    payment_mode        TEXT NOT NULL DEFAULT '',
    receipt_no          TEXT NOT NULL DEFAULT '',
    aadhaar_file        TEXT NOT NULL DEFAULT '',          -- stored file name in uploads/aadhaar/
    aadhaar_uploaded_on TEXT NOT NULL DEFAULT '',
    comments            TEXT NOT NULL DEFAULT '',
    record_status       TEXT NOT NULL DEFAULT 'Active' CHECK (record_status IN ('Active', 'Archived')),
    created_on          TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_on          TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_members_mobile  ON members (mobile);
CREATE INDEX IF NOT EXISTS idx_members_chapter ON members (chapter);
CREATE INDEX IF NOT EXISTS idx_members_status  ON members (record_status);

-- A payment is "Paid" when any subscription amount has been received.
CREATE VIEW IF NOT EXISTS member_payment_status AS
SELECT member_id, name, chapter, subscription,
       CASE WHEN subscription > 0 THEN 'Paid' ELSE 'Not Paid' END AS payment_status
FROM members
WHERE record_status = 'Active';

CREATE TABLE IF NOT EXISTS communications (
    id          TEXT PRIMARY KEY,
    created_on  TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    member_id   TEXT NOT NULL REFERENCES members (member_id),
    name        TEXT NOT NULL DEFAULT '',
    channel     TEXT NOT NULL CHECK (channel IN ('Email', 'WhatsApp')),
    recipient   TEXT NOT NULL DEFAULT '',
    subject     TEXT NOT NULL DEFAULT '',
    body        TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'Pending Approval'
                CHECK (status IN ('Pending Approval', 'Sent', 'Failed', 'Manual', 'Rejected')),
    created_by  TEXT NOT NULL DEFAULT '',
    approved_by TEXT NOT NULL DEFAULT '',
    sent_on     TEXT NOT NULL DEFAULT '',
    error       TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_comms_status ON communications (status);
CREATE INDEX IF NOT EXISTS idx_comms_member ON communications (member_id);

CREATE TABLE IF NOT EXISTS audit_log (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    ts     TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    user   TEXT NOT NULL DEFAULT '',
    action TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT ''
);
