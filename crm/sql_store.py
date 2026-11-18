"""SQLite-backed data store for the CRM.

* The database is created on first run from db/schema.sql and filled with the
  dummy records in db/seed.sql.
* Every change and its audit-log entry are written in one transaction, so a
  crash never leaves a half-applied change behind.
* A timestamped copy of the database is taken at start-up (data/backups/).
"""
from __future__ import annotations

import sqlite3
import threading
import uuid
from contextlib import closing
from datetime import datetime
from pathlib import Path

# (key, label) - order defines exports and form labels
MEMBER_FIELDS = [
    ("member_id", "Member ID"),
    ("name", "Name"),
    ("gender", "Gender"),
    ("dob", "Date of Birth"),
    ("marital_status", "Marital Status"),
    ("mobile", "Mobile"),
    ("alt_mobile", "Alternate Mobile"),
    ("email", "Email"),
    ("member_status", "Member Status"),
    ("category", "Category"),
    ("practicing", "Practicing"),
    ("position", "Position"),
    ("ob_ecm", "OB / ECM"),
    ("place", "Place"),
    ("state", "State"),
    ("chapter", "Chapter/Study Circle"),
    ("address", "Address"),
    ("pincode", "Pincode"),
    ("education", "Education"),
    ("specialization", "Specialization"),
    ("gstp_no", "GSTP No"),
    ("itp_no", "ITP No"),
    ("advocate_others", "Advocate/Others"),
    ("organization", "Organization"),
    ("subscription", "Subscription"),
    ("payment_date", "Payment Date"),
    ("payment_mode", "Payment Mode"),
    ("receipt_no", "Receipt No"),
    ("payment_status", "Payment Status"),
    ("aadhaar_file", "Aadhaar File"),
    ("aadhaar_uploaded_on", "Aadhaar Uploaded On"),
    ("comments", "Comments"),
    ("record_status", "Record Status"),
    ("created_on", "Created On"),
    ("updated_on", "Updated On"),
]
MEMBER_KEYS = [k for k, _ in MEMBER_FIELDS]
# payment_status is derived from subscription, not stored
MEMBER_COLUMNS = [k for k in MEMBER_KEYS if k != "payment_status"]

COMM_KEYS = ["id", "created_on", "member_id", "name", "channel", "recipient", "subject",
             "body", "status", "created_by", "approved_by", "sent_on", "error"]


class StoreLockedError(RuntimeError):
    """Raised when the database cannot be written (e.g. locked by another program)."""


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class SqlStore:
    def __init__(self, path: Path, backup_dir: Path, backup_keep: int, fee: int):
        self.path = Path(path)
        self.backup_dir = Path(backup_dir)
        self.backup_keep = backup_keep
        self.fee = fee
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ connection
    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _write(self, fn, user: str, action: str, detail: str):
        """Run fn(conn) and add an audit entry in the same transaction."""
        with self._lock:
            try:
                with closing(self._connect()) as conn, conn:
                    result = fn(conn)
                    conn.execute("INSERT INTO audit_log (ts, user, action, detail) VALUES (?, ?, ?, ?)",
                                 (now_str(), user, action, detail))
                    return result
            except sqlite3.OperationalError as exc:
                if "locked" in str(exc).lower():
                    raise StoreLockedError("The database is busy or locked by another program. "
                                           "Close it and try again.") from exc
                raise

    def _query(self, sql: str, params=()) -> list[dict]:
        with closing(self._connect()) as conn:
            return [dict(r) for r in conn.execute(sql, params)]

    # ------------------------------------------------------------------ setup
    def ensure(self, schema: Path, seed: Path | None = None):
        """Create the database from schema.sql (+ seed.sql) if it does not exist yet."""
        with self._lock:
            new = not self.path.exists()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with closing(self._connect()) as conn, conn:
                conn.executescript(Path(schema).read_text(encoding="utf-8"))
                if new and seed and Path(seed).exists():
                    conn.executescript(Path(seed).read_text(encoding="utf-8"))
                    n = conn.execute("SELECT COUNT(*) FROM members").fetchone()[0]
                    conn.execute("INSERT INTO audit_log (ts, user, action, detail) VALUES (?, ?, ?, ?)",
                                 (now_str(), "system", "seed", f"Loaded {n} demo members from {Path(seed).name}"))
            if not new:
                self.backup()

    def backup(self) -> Path | None:
        """Copy the live database to data/backups/ and keep the newest `backup_keep` copies."""
        if not self.path.exists():
            return None
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        target = self.backup_dir / f"{self.path.stem}_{datetime.now():%Y%m%d_%H%M%S}.db"
        with closing(self._connect()) as src, closing(sqlite3.connect(target)) as dst:
            src.backup(dst)
        backups = sorted(self.backup_dir.glob(f"{self.path.stem}_*.db"))
        for old in backups[: max(0, len(backups) - self.backup_keep)]:
            try:
                old.unlink()
            except OSError:
                pass
        return target

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _to_amount(v) -> int:
        try:
            return int(float(str(v).replace(",", "").strip() or 0))
        except ValueError:
            return 0

    def payment_status(self, m: dict) -> str:
        return "Paid" if self._to_amount(m.get("subscription")) > 0 else "Not Paid"

    def _member(self, row: dict) -> dict:
        m = {k: ("" if row.get(k) is None else row.get(k)) for k in MEMBER_COLUMNS}
        m["subscription"] = self._to_amount(m["subscription"])
        m["payment_status"] = self.payment_status(m)
        m["record_status"] = m["record_status"] or "Active"
        return m

    # ------------------------------------------------------------------ members
    def members(self, include_archived: bool = False) -> list[dict]:
        sql = "SELECT * FROM members" + ("" if include_archived else " WHERE record_status != 'Archived'")
        return [self._member(r) for r in self._query(sql)]

    def get_member(self, member_id: str) -> dict | None:
        rows = self._query("SELECT * FROM members WHERE member_id = ?", (str(member_id).strip(),))
        return self._member(rows[0]) if rows else None

    def next_member_id(self) -> str:
        rows = self._query("SELECT MAX(CAST(member_id AS INTEGER)) AS mx FROM members")
        mx = rows[0]["mx"] if rows else None
        return str(mx + 1 if mx else 100001)

    def add_member(self, data: dict, user: str) -> dict:
        if self.get_member(data["member_id"]):
            raise ValueError(f"Member ID {data['member_id']} already exists.")
        m = {k: data.get(k, "") or "" for k in MEMBER_COLUMNS}
        m["subscription"] = self._to_amount(m["subscription"])
        m["record_status"] = m["record_status"] or "Active"
        m["created_on"] = m["updated_on"] = now_str()
        cols = ", ".join(MEMBER_COLUMNS)
        marks = ", ".join("?" for _ in MEMBER_COLUMNS)
        self._write(lambda c: c.execute(f"INSERT INTO members ({cols}) VALUES ({marks})",
                                        [m[k] for k in MEMBER_COLUMNS]),
                    user, "member.create", f"{m['member_id']} {m['name']}")
        return self._member(m)

    def update_member(self, member_id: str, changes: dict, user: str, action="member.update") -> dict:
        member_id = str(member_id)
        existing = self.get_member(member_id)
        if not existing:
            raise KeyError(member_id)
        merged = {**existing, **{k: v for k, v in changes.items() if k in MEMBER_COLUMNS}}
        merged["member_id"] = member_id  # ID is immutable
        merged["subscription"] = self._to_amount(merged["subscription"])
        merged["updated_on"] = now_str()
        changed = sorted(k for k in changes if str(existing.get(k, "")) != str(merged.get(k, "")))
        cols = [k for k in MEMBER_COLUMNS if k not in ("member_id", "created_on")]
        sets = ", ".join(f"{k} = ?" for k in cols)
        self._write(lambda c: c.execute(f"UPDATE members SET {sets} WHERE member_id = ?",
                                        [merged[k] for k in cols] + [member_id]),
                    user, action, f"{member_id}: {', '.join(changed) or 'no change'}")
        return self._member(merged)

    # ------------------------------------------------------------------ communications
    def communications(self) -> list[dict]:
        return self._query("SELECT * FROM communications")

    def add_communications(self, items: list[dict], user: str) -> list[dict]:
        created = []
        for it in items:
            c = {k: it.get(k, "") or "" for k in COMM_KEYS}
            c["id"] = c["id"] or uuid.uuid4().hex[:10].upper()
            c["created_on"] = now_str()
            c["created_by"] = user
            created.append(c)
        cols, marks = ", ".join(COMM_KEYS), ", ".join("?" for _ in COMM_KEYS)
        self._write(lambda conn: conn.executemany(f"INSERT INTO communications ({cols}) VALUES ({marks})",
                                                  [[c[k] for k in COMM_KEYS] for c in created]),
                    user, "message.queue", f"{len(created)} message(s) queued")
        return created

    def update_communication(self, msg_id: str, changes: dict, user: str, action: str):
        changes = {k: v for k, v in changes.items() if k in COMM_KEYS and k != "id"}
        sets = ", ".join(f"{k} = ?" for k in changes)

        def fn(conn):
            cur = conn.execute(f"UPDATE communications SET {sets} WHERE id = ?", [*changes.values(), msg_id])
            if cur.rowcount == 0:
                raise KeyError(msg_id)

        self._write(fn, user, action, msg_id)

    # ------------------------------------------------------------------ audit
    def audit(self, limit: int = 100) -> list[dict]:
        return self._query("SELECT ts, user, action, detail FROM audit_log ORDER BY id DESC LIMIT ?", (limit,))

    def log(self, user: str, action: str, detail: str):
        self._write(lambda c: None, user, action, detail)
